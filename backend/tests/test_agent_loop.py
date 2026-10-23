"""多工具循环和停止条件。"""

import json
import unittest
from unittest.mock import AsyncMock, patch

from app.agent.workflow import build_agent_workflow


class AgentLoopTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.workflow = build_agent_workflow()

    async def test_executes_two_tools_then_stops(self):
        replies = iter([
            json.dumps({"tool": "today_reviews", "arguments": {}}),
            json.dumps({"tool": "none", "arguments": {}}),
        ])
        chat = AsyncMock(side_effect=lambda *args, **kwargs: next(replies))
        read_tool = AsyncMock(side_effect=["1 | 回顾 A", None])

        with patch("app.agent.workflow.deepseek_client.chat", chat), \
             patch("app.agent.workflow.read_tool", read_tool):
            state = await self.workflow.ainvoke({
                "user_id": "user-1",
                "query": "看看今日回顾",
                "observations": [],
                "iterations": 0,
            })

        self.assertEqual(len(state["observations"]), 1)
        self.assertEqual(state["tool_result"], "1 | 回顾 A")
        self.assertEqual(state["observations"][0]["tool"], "today_reviews")
        self.assertEqual(state["iterations"], 2)

    async def test_write_proposal_stops_loop(self):
        chat = AsyncMock(return_value=json.dumps({
            "tool": "create_note",
            "arguments": {"title": "总结", "content": "正文"},
        }))
        with patch("app.agent.workflow.deepseek_client.chat", chat):
            state = await self.workflow.ainvoke({
                "user_id": "user-1",
                "query": "创建总结笔记",
                "observations": [],
                "iterations": 0,
            })

        self.assertEqual(state["proposal"]["tool"], "create_note")
        self.assertEqual(state["iterations"], 1)


if __name__ == "__main__":
    unittest.main()
