"""第 49 章 LangGraph 固定节点流程。"""

import json
import unittest
from unittest.mock import AsyncMock, patch

from app.agent.workflow import build_agent_workflow


class AgentWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.workflow = build_agent_workflow()

    async def test_none_choice_has_no_tool_result_or_proposal(self):
        with patch(
            "app.agent.workflow.deepseek_client.chat",
            AsyncMock(return_value=json.dumps({"tool": "none", "arguments": {}})),
        ):
            state = await self.workflow.ainvoke({
                "user_id": "user-1", "query": "普通问题",
            })

        self.assertEqual(state["choice"]["tool"], "none")
        self.assertIsNone(state["proposal"])
        self.assertIsNone(state["tool_result"])

    async def test_read_tool_runs_with_jwt_user(self):
        read_tool = AsyncMock(return_value="本人笔记")
        with patch(
            "app.agent.workflow.deepseek_client.chat",
            AsyncMock(side_effect=[
                json.dumps({
                    "tool": "search_notes",
                    "arguments": {"query": "FastAPI"},
                }),
                json.dumps({"tool": "none", "arguments": {}}),
            ]),
        ), patch("app.agent.workflow.read_tool", read_tool):
            state = await self.workflow.ainvoke({
                "user_id": "user-1", "query": "搜我的 FastAPI 笔记",
            })

        self.assertEqual(state["observations"][0]["result"], "本人笔记")
        self.assertEqual(read_tool.await_args.args[1], "user-1")

    async def test_write_choice_returns_proposal_only(self):
        with patch(
            "app.agent.workflow.deepseek_client.chat",
            AsyncMock(return_value=json.dumps({
                "tool": "create_note",
                "arguments": {"title": "新笔记", "content": "正文"},
            })),
        ):
            state = await self.workflow.ainvoke({
                "user_id": "user-1", "query": "创建一篇新笔记",
            })

        self.assertEqual(state["proposal"]["tool"], "create_note")
        self.assertIsNone(state["tool_result"])


if __name__ == "__main__":
    unittest.main()
