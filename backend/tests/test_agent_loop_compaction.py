"""第 67 篇：循环和上下文压缩的离线行为验证。"""
import copy
import json
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import httpx
from fastapi import HTTPException
from app.agent.chat_loop import run_loop
from app.agent.loop_protocol import ContextLimitError, TOOLS
from app.agent.loop_tools import dispatch, pack_result
from app.agent.session_lease import session_lease
from app.core.settings import settings
from app.services.chat_context import AgentContext
from app.services.chat_memory_store import ChatMemoryStore
from app.services.deepseek_client import deepseek_client
from app.services import chat_stream_service as stream_service


def call(name, arguments=None, identifier="call-1"):
    return {"role": "assistant", "content": "", "tool_calls": [{
        "id": identifier, "type": "function", "function": {
            "name": name, "arguments": json.dumps(arguments or {}),
        },
    }]}


def summary():
    return json.dumps({"goal": "理解缓存", "constraints": ["用中文"],
        "facts": ["讨论过 Redis"], "completed": [], "open_questions": [], "sources": []})


class FakeStore:
    user_id = "user-1"
    session_id = "session-1"

    def __init__(self):
        self.artifacts = {}

    async def archive(self, kind, content):
        key = f"artifact-{len(self.artifacts)}"
        self.artifacts[key] = content
        return key

    async def read_artifact(self, artifact_id, offset):
        raw = self.artifacts[artifact_id]
        return {"content": raw[offset:offset + 2000]}


class LoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_tools_and_followup_retrieval_share_message_chain(self):
        captured = []
        replies = [call("search_rag", {"query": "Redis 缓存"}),
                   call("search_rag", {"query": "Redis 缓存击穿"}, "call-2"),
                   {"role": "assistant", "content": "结合两次证据回答"}]

        async def model(messages, tools):
            captured.append(copy.deepcopy(messages))
            return replies.pop(0)

        with patch("app.agent.chat_loop.deepseek_client.complete_turn", model), patch(
            "app.agent.chat_loop.dispatch", AsyncMock(side_effect=[
                {"result": "缓存基本证据"}, {"result": "击穿处理证据"},
            ]),
        ):
            events = [e async for e in run_loop(AgentContext(), FakeStore(), "详细解释")]
        self.assertEqual(captured[1][-1]["role"], "tool")
        self.assertEqual(captured[1][-1]["tool_call_id"], "call-1")
        self.assertIn("缓存基本证据", captured[1][-1]["content"])
        self.assertEqual(captured[2][-1]["tool_call_id"], "call-2")
        self.assertEqual(events[-1], {"type": "answer", "content": "结合两次证据回答"})

    async def test_write_proposal_stops_without_execution(self):
        proposal = {"tool": "create_note", "arguments": {"title": "缓存"}, "description": "创建"}
        context = AgentContext()
        with patch("app.agent.chat_loop.deepseek_client.complete_turn", AsyncMock(return_value=call("create_note"))), patch(
            "app.agent.chat_loop.dispatch", AsyncMock(return_value={"proposal": proposal}),
        ) as dispatch_mock:
            events = [e async for e in run_loop(context, FakeStore(), "创建笔记")]
        self.assertEqual(events[-1]["type"], "proposal")
        self.assertEqual(len(context.messages), 1)
        dispatch_mock.assert_awaited_once()

    async def test_duplicate_tool_is_bounded(self):
        replies = [call("today_reviews", identifier=f"call-{i}") for i in range(3)]
        with patch("app.agent.chat_loop.deepseek_client.complete_turn", AsyncMock(side_effect=replies)), patch(
            "app.agent.chat_loop.dispatch", AsyncMock(return_value={"result": "没有记录"}),
        ) as dispatch_mock:
            events = [e async for e in run_loop(AgentContext(), FakeStore(), "回顾")]
        self.assertEqual(events[-1]["type"], "answer")
        self.assertEqual(dispatch_mock.await_count, 2)

    async def test_large_result_is_recoverable(self):
        store = FakeStore()
        raw = "abcdef" * 2000
        packed = json.loads(await pack_result(store, "search_rag", raw))
        self.assertTrue(packed["truncated"])
        self.assertEqual(store.artifacts[packed["artifact_id"]], raw)
        self.assertEqual((await store.read_artifact(packed["artifact_id"], 2000))["content"], raw[2000:4000])

    async def test_tool_arguments_reject_user_injection(self):
        result = await dispatch("note_stats", {"user_id": "another-user"}, FakeStore())
        self.assertIn("error", result["result"])

    async def test_unknown_tool_is_not_executed(self):
        result = await dispatch("bash", {"command": "anything"}, FakeStore())
        self.assertIn("error", result["result"])


class CompressionTests(unittest.IsolatedAsyncioTestCase):
    def history(self):
        messages = []
        for i in range(4):
            messages.extend([{"role": "user", "content": f"问题{i}"},
                             {"role": "assistant", "content": f"回答{i}"}])
        return messages

    async def test_summary_preserves_recent_turns_and_full_archive(self):
        context = AgentContext(messages=self.history())
        original = copy.deepcopy(context.messages)
        store = FakeStore()
        with patch.object(deepseek_client, "chat", AsyncMock(return_value=summary())):
            changed = await context.prepare("系统", TOOLS, store.archive, force=True)
        self.assertTrue(changed)
        self.assertEqual(context.messages, original[-4:])
        self.assertEqual(json.loads(next(iter(store.artifacts.values())))["messages"], original)
        self.assertEqual(context.summary["constraints"], ["用中文"])

    async def test_failed_summary_keeps_history(self):
        original = self.history()
        context = AgentContext(messages=copy.deepcopy(original))
        with patch.object(deepseek_client, "chat", AsyncMock(return_value="not-json")):
            with self.assertRaises(ValueError):
                await context.prepare("系统", TOOLS, FakeStore().archive, force=True)
        self.assertEqual(context.messages, original)
        self.assertEqual(context.summary, {})

    async def test_tool_pair_is_not_split(self):
        messages = self.history()
        messages[4:4] = [call("note_stats"), {"role": "tool", "tool_call_id": "call-1", "content": "统计"}]
        context = AgentContext(messages=messages)
        with patch.object(deepseek_client, "chat", AsyncMock(return_value=summary())):
            await context.prepare("系统", TOOLS, FakeStore().archive, force=True)
        self.assertFalse(any(m["role"] == "tool" for m in context.messages))
        self.assertEqual(context.messages[0]["content"], "问题2")

    async def test_newest_tool_results_are_preserved_during_micro_compaction(self):
        context = AgentContext(messages=[{"role": "user", "content": "当前问题"}])
        for i in range(4):
            context.messages.extend([call("note_stats", identifier=f"c{i}"), {
                "role": "tool", "tool_call_id": f"c{i}", "content": json.dumps({
                    "artifact_id": f"a{i}", "preview": "长" * 2500,
                }, ensure_ascii=False),
            }])
        latest = context.messages[-1]["content"]
        await context.prepare("系统", [], FakeStore().archive, force=True)
        self.assertEqual(context.messages[-1]["content"], latest)
        self.assertNotIn("preview", context.messages[2]["content"])

    async def test_oversized_current_request_fails_without_truncating(self):
        original = "字" * 30000
        context = AgentContext(messages=[{"role": "user", "content": original}])
        with self.assertRaises(ValueError):
            await context.prepare("系统", TOOLS, FakeStore().archive)
        self.assertEqual(context.messages[0]["content"], original)

    async def test_context_rejection_retries_once_after_compression(self):
        context = AgentContext(messages=self.history())
        with patch.object(deepseek_client, "complete_turn", AsyncMock(side_effect=[
            ContextLimitError(), {"role": "assistant", "content": "继续解释"},
        ])) as model, patch.object(deepseek_client, "chat", AsyncMock(return_value=summary())):
            events = [e async for e in run_loop(context, FakeStore(), "继续")]
        self.assertEqual(model.await_count, 2)
        self.assertEqual(events[-1]["type"], "answer")

    async def test_second_context_rejection_stops(self):
        with patch.object(deepseek_client, "complete_turn", AsyncMock(side_effect=ContextLimitError())) as model, patch.object(
            deepseek_client, "chat", AsyncMock(return_value=summary()),
        ):
            events = [e async for e in run_loop(AgentContext(messages=self.history()), FakeStore(), "继续")]
        self.assertEqual(events[-1]["type"], "answer")
        self.assertEqual(model.await_count, 2)


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, payload, status=200):
        real_client = httpx.AsyncClient
        sent = []
        def handler(request):
            sent.append(json.loads(request.content))
            return httpx.Response(status, json=payload)
        with patch("app.services.deepseek_client._api_keys", return_value=["fake-test-key"]), patch(
            "app.services.deepseek_client.httpx.AsyncClient",
            side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
        ):
            result = await deepseek_client.complete_turn([{"role": "user", "content": "测试"}], TOOLS)
        return result, sent

    async def test_native_tool_message_roundtrip(self):
        result, sent = await self.request({"choices": [{"message": call("note_stats"), "finish_reason": "tool_calls"}]})
        self.assertEqual(result["tool_calls"][0]["id"], "call-1")
        self.assertFalse(sent[0]["parallel_tool_calls"])
        self.assertEqual(sent[0]["tools"], TOOLS)

    async def test_nullable_tool_calls_in_final_answer(self):
        result, _ = await self.request({"choices": [{"message": {
            "role": "assistant", "content": "答案", "tool_calls": None,
        }, "finish_reason": "stop"}]})
        self.assertEqual(result["content"], "答案")

    async def test_truncated_tool_arguments_are_rejected(self):
        with self.assertRaises(HTTPException):
            await self.request({"choices": [{"message": call("note_stats"), "finish_reason": "length"}]})

    async def test_native_context_error_has_distinct_type(self):
        with self.assertRaises(ContextLimitError):
            await self.request({"error": {"code": "context_length_exceeded"}}, status=400)


class BoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_memory_load_only_appends_after_watermark(self):
        saved = {"through_id": 2, "summary": {"goal": "缓存"}, "archives": [],
                 "messages": [{"role": "user", "content": "旧问题"}, {"role": "assistant", "content": "旧回答"}]}
        rows = [SimpleNamespace(id=3, role="user", content="新问题"),
                SimpleNamespace(id=4, role="assistant", content="新回答")]
        db = SimpleNamespace(scalar=AsyncMock(return_value=4), execute=AsyncMock(
            return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows)),
        ))
        @asynccontextmanager
        async def fake_db():
            yield db
        with patch("app.services.chat_memory_store.AsyncSessionLocal", fake_db), patch(
            "app.services.chat_memory_store.chat_session_service.owned",
            AsyncMock(return_value=SimpleNamespace(metadata_={"agent_context": saved})),
        ):
            context = await ChatMemoryStore("u1", "s1").load("系统", [])
        self.assertEqual([m["content"] for m in context.messages], ["旧问题", "旧回答", "新问题", "新回答"])
        self.assertEqual(len(saved["messages"]), 2)
        params = db.execute.await_args.args[0].compile().params
        self.assertIn(2, params.values())
        self.assertIn(4, params.values())

    async def test_finish_commits_context_and_chat_together(self):
        session = SimpleNamespace(metadata_={"label": "保留"}, pending_run_id=None)
        added = []
        async def flush():
            added[-1].id = 99
        db = SimpleNamespace(scalar=AsyncMock(return_value=session), add=added.append,
                             flush=flush, commit=AsyncMock())
        @asynccontextmanager
        async def fake_db():
            yield db
        with patch("app.services.chat_memory_store.AsyncSessionLocal", fake_db):
            await ChatMemoryStore("u1", "s1").finish("问题", "答案", AgentContext())
        self.assertEqual([row.role for row in added], ["user", "assistant"])
        self.assertEqual(session.metadata_["agent_context"]["through_id"], 99)
        self.assertEqual(session.metadata_["label"], "保留")
        db.commit.assert_awaited_once()

    async def test_pending_request_prevents_new_loop(self):
        db = SimpleNamespace(commit=AsyncMock())
        @asynccontextmanager
        async def fake_db():
            yield db
        with patch("app.services.chat_memory_store.AsyncSessionLocal", fake_db), patch(
            "app.services.chat_memory_store.chat_session_service.ensure",
            AsyncMock(return_value=SimpleNamespace(pending_run_id="run1")),
        ):
            with self.assertRaises(HTTPException) as caught:
                await ChatMemoryStore("u1", "s1").start("s1", "新问题")
        self.assertEqual(caught.exception.detail, "PENDING_EXISTS")
        db.commit.assert_not_awaited()

    async def test_artifact_query_is_scoped_to_owner_and_session(self):
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(first=lambda: None)))
        @asynccontextmanager
        async def fake_db():
            yield db
        with patch("app.services.chat_memory_store.AsyncSessionLocal", fake_db), patch(
            "app.services.chat_memory_store.chat_session_service.owned", AsyncMock(),
        ):
            with self.assertRaises(HTTPException):
                await ChatMemoryStore("u1", "s1").read_artifact("foreign", 0)
        params = db.execute.await_args.args[0].compile().params
        self.assertIn("u1", params.values())
        self.assertIn("s1", params.values())
        self.assertIn("foreign", params.values())

    async def test_lease_release_on_error(self):
        redis = SimpleNamespace(set=AsyncMock(return_value=True), eval=AsyncMock(), aclose=AsyncMock())
        with patch("app.agent.session_lease.get_redis", return_value=redis):
            with self.assertRaises(ValueError):
                async with session_lease("u1", "s1"):
                    raise ValueError("模拟失败")
        redis.eval.assert_awaited_once()
        redis.aclose.assert_awaited_once()

    async def test_busy_session_does_not_release_other_lease(self):
        redis = SimpleNamespace(set=AsyncMock(return_value=False), eval=AsyncMock(), aclose=AsyncMock())
        with patch("app.agent.session_lease.get_redis", return_value=redis):
            with self.assertRaises(HTTPException):
                async with session_lease("u1", "s1"):
                    self.fail("不应取得租约")
        redis.eval.assert_not_awaited()

    async def test_sse_commits_before_answer_and_keeps_session_id(self):
        order = []
        store = SimpleNamespace(start=AsyncMock(), load=AsyncMock(return_value=AgentContext()))
        async def finish(*args):
            order.append("saved")
        store.finish = finish
        @asynccontextmanager
        async def lease(*args):
            yield
        async def loop(*args):
            yield {"type": "answer", "content": "最终答案"}
        with patch.object(stream_service, "session_lease", lease), patch.object(
            stream_service, "ChatMemoryStore", return_value=store,
        ), patch.object(stream_service, "run_loop", loop):
            frames = []
            async for event in stream_service.chat_events("u1", "问题", "s1", "s1"):
                item = json.loads(event[6:])
                if item["type"] == "response":
                    self.assertEqual(order, ["saved"])
                frames.append(item)
        self.assertEqual(frames[-1]["type"], "done")
        self.assertEqual(frames[-1]["session_id"], "s1")

    async def test_sse_proposal_keeps_approval_contract(self):
        store = SimpleNamespace(start=AsyncMock(), load=AsyncMock(return_value=AgentContext()), finish=AsyncMock())
        proposal = {"tool": "create_note", "arguments": {"title": "标题"}, "description": "申请创建"}
        @asynccontextmanager
        async def lease(*args):
            yield
        async def loop(*args):
            yield {"type": "proposal", "proposal": proposal}
        with patch.object(stream_service, "session_lease", lease), patch.object(
            stream_service, "ChatMemoryStore", return_value=store,
        ), patch.object(stream_service, "run_loop", loop), patch.object(
            stream_service, "save_pending", AsyncMock(return_value=SimpleNamespace(id="run1")),
        ):
            frames = [json.loads(e[6:]) async for e in stream_service.chat_events("u1", "创建", "s1", None)]
        self.assertEqual(frames[0]["type"], "interrupt")
        self.assertEqual(frames[0]["payload"]["action_requests"][0]["name"], "create_note")
        store.finish.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
