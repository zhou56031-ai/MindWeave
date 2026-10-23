"""回答上下文的行为回归：不调用真实模型，不写入数据库。"""

import json
import unittest
from contextlib import ExitStack, asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from app.services.chat_context import AgentContext, bounded_history, tool_evidence
from app.services.chat_session_service import chat_session_service
from app.services import chat_stream_service as service
from app.rag.agentic_service import collect_evidence
from app.rag.answerability import Answerability
from app.agent.workflow import build_agent_workflow, choose


class FakeDB:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *args):
        return False


class ContextTests(unittest.TestCase):
    def test_history_keeps_recent_pairs_and_bounds_size(self):
        history = []
        for index in range(9):
            history.extend([
                {"role": "user", "content": f"问题{index}"},
                {"role": "assistant", "content": f"回答{index}"},
            ])
        selected = bounded_history(history)
        self.assertEqual(len(selected), 12)
        self.assertEqual(selected[0]["content"], "问题3")
        self.assertEqual(selected[-1]["content"], "回答8")
        huge = bounded_history([
            {"role": role, "content": "字" * 9000}
            for role in ["user", "assistant"] * 9
        ])
        self.assertLessEqual(sum(len(m["content"]) for m in huge), 12000)
        self.assertEqual(huge[0]["role"], "user")

    def test_only_real_read_results_are_handed_over(self):
        evidence = json.loads(tool_evidence({"observations": [
            {"tool": "today_reviews", "result": "事务练习"},
            {"tool": "note_stats", "result": "3 篇"},
            {"tool": "none", "result": "错误的停止日志"},
            {"tool": "create_note", "result": "尚未审批的提案"},
        ]}))
        self.assertEqual([item["tool"] for item in evidence],
                         ["today_reviews", "note_stats"])


class ChatQualityTests(unittest.IsolatedAsyncioTestCase):
    async def test_followup_keeps_tool_decision_output_contract(self):
        chat = AsyncMock(return_value='{"tool":"none","arguments":{}}')
        with patch("app.agent.workflow.deepseek_client.chat", chat):
            result = await choose({
                "query": "只回答刚才的名字，不要调用工具",
                "conversation": [
                    {"role": "user", "content": "名字是星桥"},
                    {"role": "assistant", "content": "确认"},
                ],
                "observations": [],
            })
        prompt = chat.await_args.args[0][-1]["content"]
        self.assertIn("当前任务是选择工具，不是回答上面的用户问题", prompt)
        self.assertIn('{"tool":"none","arguments":{}}', prompt)
        self.assertTrue(chat.await_args.kwargs["json_mode"])
        self.assertEqual(result["choice"], {"tool": "none", "arguments": {}})

    async def test_foreign_session_does_not_read_messages(self):
        db = SimpleNamespace(execute=AsyncMock())
        with patch.object(chat_session_service, "owned", AsyncMock(
            side_effect=HTTPException(status_code=404, detail="会话不存在"),
        )) as owned:
            with self.assertRaises(HTTPException):
                await chat_session_service.history_for_model(db, "u1", "foreign")
        owned.assert_awaited_once_with(db, "u1", "foreign")
        db.execute.assert_not_awaited()

    async def test_history_query_restores_chronological_order(self):
        rows = [
            SimpleNamespace(role="assistant", content="Redis"),
            SimpleNamespace(role="user", content="介绍缓存"),
        ]
        result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))
        db = SimpleNamespace(execute=AsyncMock(return_value=result))
        with patch.object(chat_session_service, "owned", AsyncMock(
            return_value=SimpleNamespace(id="session1"),
        )):
            history = await chat_session_service.history_for_model(db, "u1", "session1")
        self.assertEqual([m["role"] for m in history], ["user", "assistant"])
        self.assertEqual(history[-1]["content"], "Redis")

    async def test_final_answer_receives_history_and_all_tool_results(self):
        history = [
            {"role": "user", "content": "比较 MySQL 和 Redis"},
            {"role": "assistant", "content": "第二个是 Redis"},
        ]
        context = AgentContext(messages=list(history))
        store = SimpleNamespace(
            start=AsyncMock(), load=AsyncMock(return_value=context),
            finish=AsyncMock(), archive=AsyncMock(return_value="artifact-1"),
        )
        captured = []
        replies = [
            {"role": "assistant", "content": "", "tool_calls": [{
                "id": "call-1", "type": "function",
                "function": {"name": "today_reviews", "arguments": "{}"},
            }]},
            {"role": "assistant", "content": "", "tool_calls": [{
                "id": "call-2", "type": "function",
                "function": {"name": "note_stats", "arguments": "{}"},
            }]},
            {"role": "assistant", "content": "Redis 可以保存缓存。"},
        ]

        async def model(messages, tools):
            captured.append(list(messages))
            return replies.pop(0)

        @asynccontextmanager
        async def lease(*args):
            yield

        with ExitStack() as stack:
            stack.enter_context(patch.object(service, "session_lease", lease))
            stack.enter_context(patch.object(service, "ChatMemoryStore", return_value=store))
            stack.enter_context(patch("app.agent.chat_loop.deepseek_client.complete_turn", model))
            stack.enter_context(patch("app.agent.chat_loop.dispatch", AsyncMock(side_effect=[
                {"result": "事务练习"}, {"result": "3 篇"},
            ])))
            frames = [json.loads(frame[6:]) async for frame in service.chat_events(
                "u1", "第二个适合存什么", "session1", "session1",
            )]
        self.assertEqual(captured[-1][1:3], history)
        tool_messages = [m["content"] for m in captured[-1] if m["role"] == "tool"]
        self.assertIn("事务练习", tool_messages[0])
        self.assertIn("3 篇", tool_messages[1])
        self.assertEqual(frames[-1]["type"], "done")
        self.assertEqual(frames[-2]["type"], "response")
        store.finish.assert_awaited_once_with(
            "第二个适合存什么", "Redis 可以保存缓存。", context,
        )

    async def test_tool_decision_uses_history_and_keeps_result_when_stopping(self):
        history = [{"role": "user", "content": "讨论回顾"},
                   {"role": "assistant", "content": "可以列出今日回顾"}]
        chat = AsyncMock(side_effect=[
            json.dumps({"tool": "today_reviews", "arguments": {}}),
            json.dumps({"tool": "none", "arguments": {}}),
        ])
        with patch("app.agent.workflow.deepseek_client.chat", chat), patch(
            "app.agent.workflow.read_tool", AsyncMock(return_value="事务练习"),
        ), patch("app.agent.workflow.AsyncSessionLocal", FakeDB):
            result = await build_agent_workflow().ainvoke({
                "user_id": "u1", "query": "列出来", "conversation": history,
                "observations": [], "iterations": 0,
            })
        self.assertEqual(chat.await_args_list[0].args[0][1:3], history)
        self.assertEqual(result["tool_result"], "事务练习")
        self.assertEqual(len(result["observations"]), 1)

    async def test_retrieval_evaluates_resolved_question(self):
        history = [{"role": "user", "content": "比较 MySQL 和 Redis"},
                   {"role": "assistant", "content": "第二个是 Redis"}]
        chat = AsyncMock(return_value=json.dumps({
            "resolved_question": "Redis 为什么快？", "queries": ["Redis 性能"],
        }))
        evaluator = AsyncMock(return_value=Answerability(answerable=True, confidence=0.9))
        with patch("app.rag.agentic_service.deepseek_client.chat", chat), patch(
            "app.rag.agentic_service.search_graph", AsyncMock(return_value=[]),
        ), patch("app.rag.agentic_service.search", AsyncMock(return_value=[])), patch(
            "app.rag.agentic_service.evaluate", evaluator,
        ):
            await collect_evidence(object(), "u1", "第二个为什么快", history=history)
        self.assertEqual(chat.await_args.args[0][1:3], history)
        self.assertEqual(evaluator.await_args.args[0], "Redis 为什么快？")


if __name__ == "__main__":
    unittest.main()
