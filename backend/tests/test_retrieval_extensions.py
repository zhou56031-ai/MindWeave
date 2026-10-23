"""第 51 章写作流、关联计算与重排。"""

import unittest
from unittest.mock import AsyncMock, patch

from app.rag.related import cosine
from app.rag.reorder import reorder
from app.services.note_ai_service import note_ai_service


class WriterAssistTests(unittest.IsolatedAsyncioTestCase):
    async def test_assist_streams_and_limits_input(self):
        captured = {}

        async def fake_stream(messages, *, max_tokens):
            captured["messages"] = messages
            captured["max_tokens"] = max_tokens
            yield "建议"

        with patch(
            "app.services.note_ai_service.deepseek_client.stream_chat",
            fake_stream,
        ):
            parts = [
                part async for part in note_ai_service.assist_chunks(
                    "x" * 7000, "expand",
                )
            ]

        self.assertEqual(parts, ["建议"])
        self.assertEqual(captured["messages"][1]["content"], "x" * 6000)
        self.assertIn("扩写原文", captured["messages"][0]["content"])
        self.assertNotIn("已保存笔记", captured["messages"][0]["content"].replace(
            "不得宣称已保存笔记", "",
        ))


class ReorderTests(unittest.IsolatedAsyncioTestCase):
    async def test_reorders_by_cosine_and_keeps_ties_stable(self):
        vectors = [
            [1.0, 0.0],
            [0.0, 1.0],
            [1.0, 0.0],
            [1.0, 0.0],
        ]

        with patch(
            "app.rag.reorder.embed_many",
            AsyncMock(return_value=vectors),
        ):
            ranked = await reorder("query", ["无关", "完全相关", "并列相关"])

        self.assertEqual(
            [item["document"] for item in ranked],
            ["完全相关", "并列相关", "无关"],
        )
        self.assertEqual(ranked[0]["similarity"], 1.0)

    async def test_empty_documents_do_not_load_model(self):
        embed_many = AsyncMock()
        with patch("app.rag.reorder.embed_many", embed_many):
            result = await reorder("query", [])

        self.assertEqual(result, [])
        embed_many.assert_not_awaited()

    def test_cosine_clamps_to_probability_range(self):
        self.assertEqual(cosine([1.0, 0.0], [1.0, 0.0]), 1.0)
        self.assertEqual(cosine([1.0, 0.0], [-1.0, 0.0]), 0.0)


if __name__ == "__main__":
    unittest.main()
