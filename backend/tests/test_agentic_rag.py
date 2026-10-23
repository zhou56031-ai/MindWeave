"""第 47 章查询规划、来源去重与 SSE 证据事件。"""

import json
import unittest
from unittest.mock import AsyncMock, patch

from app.rag.agentic_service import QueryPlan, collect_evidence
from app.rag.answerability import Answerability
from app.schemas.models import RetrievalHit


def hit(source_id: str, score: int, source_kind: str = "note") -> RetrievalHit:
    return RetrievalHit(
        source_kind=source_kind,
        source_id=source_id,
        title="资料 " + source_id,
        snippet="证据片段 " + source_id,
        score=score,
    )


class AgenticPlanTests(unittest.IsolatedAsyncioTestCase):
    async def test_plans_queries_and_deduplicates_sources(self):
        chat = AsyncMock(return_value=json.dumps({
            "queries": ["FastAPI 依赖注入", "请求级数据库会话"],
        }))

        async def fake_search(db, user_id, query):
            if query == "FastAPI 依赖注入":
                return [hit("note-1", 10), hit("note-2", 4)]
            return [hit("note-1", 20)]

        with patch("app.rag.agentic_service.deepseek_client.chat", chat), \
             patch("app.rag.agentic_service.search_graph", AsyncMock(return_value=[])), \
             patch("app.rag.agentic_service.evaluate", AsyncMock(return_value=Answerability(
                 answerable=True, confidence=0.9, reason="可答",
             ))), \
             patch("app.rag.agentic_service.search_web", AsyncMock(return_value=[])), \
             patch("app.rag.agentic_service.search", fake_search):
            hits, context, answerability, used_web = await collect_evidence(
                object(), "user-1", "FastAPI 如何使用请求级数据库会话？",
            )

        self.assertEqual([item.source_id for item in hits], ["note-1", "note-2"])
        self.assertEqual(hits[0].score, 20)
        self.assertTrue(answerability.answerable)
        self.assertFalse(used_web)
        self.assertIn("note-1", context)

    async def test_invalid_plan_falls_back_to_original_question(self):
        calls = []

        async def fake_search(db, user_id, query):
            calls.append(query)
            return [hit("note-1", 1)]

        with patch(
            "app.rag.agentic_service.deepseek_client.chat",
            AsyncMock(return_value="not json"),
        ), patch(
            "app.rag.agentic_service.search_graph",
            AsyncMock(return_value=[]),
        ), patch(
            "app.rag.agentic_service.evaluate",
            AsyncMock(return_value=Answerability(
                answerable=True, confidence=0.8, reason="可答",
            )),
        ), patch(
            "app.rag.agentic_service.search_web",
            AsyncMock(return_value=[]),
        ), patch("app.rag.agentic_service.search", fake_search):
            await collect_evidence(object(), "user-1", "原始问题")

        self.assertEqual(calls, ["原始问题"])

    def test_query_plan_limits_query_count(self):
        with self.assertRaises(Exception):
            QueryPlan.model_validate({"queries": ["a", "b", "c", "d"]})


if __name__ == "__main__":
    unittest.main()
