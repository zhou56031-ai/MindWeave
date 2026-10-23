"""工具循环上限时的降级：给部分答案，而不是抛错。"""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agent.chat_loop import run_loop


class FakeContext:
    def __init__(self):
        self.messages = []

    def request_messages(self, system):
        return [{"role": "system", "content": system}, *self.messages]

    async def prepare(self, *args, **kwargs):
        return False

    def input_bytes(self, system, tools):
        return 128


def tool_call(identifier: str):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": identifier,
            "type": "function",
            "function": {"name": "search_notes", "arguments": "{}"},
        }],
    }


class AbortTests(unittest.IsolatedAsyncioTestCase):
    async def test_max_steps_returns_partial_answer(self):
        context = FakeContext()
        store = SimpleNamespace(archive=None)
        with patch("app.agent.chat_loop.deepseek_client.complete_turn",
                   AsyncMock(return_value=tool_call("call-1"))), \
             patch("app.agent.chat_loop.dispatch", AsyncMock(return_value={"result": "ok"})), \
             patch("app.agent.chat_loop.pack_result", AsyncMock(return_value="ok")), \
             patch("app.agent.chat_loop.deepseek_client.chat",
                   AsyncMock(return_value="这是基于已查资料的部分答案")), \
             patch("app.core.settings.settings.AGENT_MAX_STEPS", 1):
            chunks = [chunk async for chunk in run_loop(context, store, "查一下")]

        self.assertEqual(chunks[-1]["type"], "answer")
        self.assertIn("部分答案", chunks[-1]["content"])

    async def test_repeated_tool_stops_with_partial_answer(self):
        context = FakeContext()
        store = SimpleNamespace(archive=None)
        calls = [tool_call("call-1"), tool_call("call-2"), tool_call("call-3")]
        with patch("app.agent.chat_loop.deepseek_client.complete_turn",
                   AsyncMock(side_effect=calls)), \
             patch("app.agent.chat_loop.dispatch", AsyncMock(return_value={"result": "ok"})), \
             patch("app.agent.chat_loop.pack_result", AsyncMock(return_value="ok")), \
             patch("app.agent.chat_loop.deepseek_client.chat",
                   AsyncMock(return_value="降级答案")):
            chunks = [chunk async for chunk in run_loop(context, store, "查一下")]

        self.assertEqual(chunks[-1], {"type": "answer", "content": "降级答案"})


if __name__ == "__main__":
    unittest.main()
