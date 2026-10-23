"""图实体候选与 Agentic RAG 图/文合并。"""

import json
import unittest
from unittest.mock import AsyncMock, patch

from app.rag.query_entities import extract_query_entities
from app.rag.answerability import Answerability
from app.schemas.models import RetrievalHit


class QueryEntityTests(unittest.IsolatedAsyncioTestCase):
    async def test_llm_entities_are_cleaned_and_deduplicated(self):
        with patch(
            "app.rag.query_entities.deepseek_client.chat",
            AsyncMock(return_value=json.dumps([" FastAPI ", "FastAPI", "Pydantic"])),
        ):
            values = await extract_query_entities("FastAPI 和 Pydantic")

        self.assertEqual(values, ["FastAPI", "Pydantic"])

    async def test_invalid_output_falls_back_to_rule_split(self):
        with patch(
            "app.rag.query_entities.deepseek_client.chat",
            AsyncMock(return_value="not json"),
        ):
            values = await extract_query_entities("FastAPI 和 Pydantic 的关系")

        self.assertIn("FastAPI", values)
        self.assertIn("Pydantic", values)


class AgenticGraphMergeTests(unittest.IsolatedAsyncioTestCase):
    async def test_graph_and_text_hits_merge_by_source(self):
        from app.rag.agentic_service import collect_evidence

        graph_hit = RetrievalHit(
            source_kind="graph", source_id="e1", title="FastAPI",
            snippet="框架", score=1000,
        )
        text_hit = RetrievalHit(
            source_kind="note", source_id="n1", title="笔记",
            snippet="FastAPI 正文", score=900,
        )
        duplicate_text = RetrievalHit(
            source_kind="note", source_id="n1", title="笔记",
            snippet="旧分数", score=500,
        )

        with patch(
            "app.rag.agentic_service.deepseek_client.chat",
            AsyncMock(return_value=json.dumps({"queries": ["FastAPI"]})),
        ), patch(
            "app.rag.agentic_service.search_graph",
            AsyncMock(return_value=[graph_hit]),
        ), patch(
            "app.rag.agentic_service.search",
            AsyncMock(return_value=[text_hit, duplicate_text]),
        ), patch(
            "app.rag.agentic_service.evaluate",
            AsyncMock(return_value=Answerability(
                answerable=True, confidence=0.9, reason="可答",
            )),
        ), patch(
            "app.rag.agentic_service.search_web",
            AsyncMock(return_value=[]),
        ):
            hits, context, answerability, used_web = await collect_evidence(
                object(), "user-1", "FastAPI",
            )

        self.assertEqual([hit.source_id for hit in hits], ["e1", "n1"])
        self.assertIn("graph:e1", context)
        self.assertTrue(answerability.answerable)
        self.assertFalse(used_web)


if __name__ == "__main__":
    unittest.main()
