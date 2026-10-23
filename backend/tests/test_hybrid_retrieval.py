"""第 46 章 RRF 融合与字面检索降级。"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.rag.hybrid_retrieval import search
from app.schemas.models import RetrievalHit


class FakeRecord:
    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, key: str):
        return self._data[key]

    def data(self) -> dict:
        return self._data


class HybridRetrievalTests(unittest.IsolatedAsyncioTestCase):
    async def test_merges_vector_and_fulltext_by_chunk_id(self):
        vector_rows = [
            FakeRecord({"id": "c1", "kind": "note", "sid": "s1",
                        "title": "A", "text": "FastAPI 请求级会话"}),
            FakeRecord({"id": "c2", "kind": "doc", "sid": "s2",
                        "title": "B", "text": "数据库连接"}),
        ]
        word_rows = [
            FakeRecord({"id": "c1", "kind": "note", "sid": "s1",
                        "title": "A", "text": "FastAPI 请求级会话"}),
            FakeRecord({"id": "c3", "kind": "note", "sid": "s3",
                        "title": "C", "text": "依赖注入"}),
        ]
        driver = SimpleNamespace(execute_query=AsyncMock(side_effect=[
            SimpleNamespace(records=vector_rows),
            SimpleNamespace(records=word_rows),
        ]))

        with patch("app.rag.hybrid_retrieval.embed", AsyncMock(return_value=[0.1])), \
             patch("app.rag.hybrid_retrieval.graph_driver", return_value=driver):
            hits = await search(object(), "user-1", "FastAPI")

        self.assertEqual([hit.source_id for hit in hits], ["s1", "s2", "s3"])
        self.assertEqual(len(hits), 3)
        self.assertEqual(hits[0].source_kind, "note")
        self.assertGreater(hits[0].score, hits[1].score)

    async def test_embedding_failure_falls_back_to_mysql(self):
        expected = [RetrievalHit(
            source_kind="note", source_id="note-1", title="标题",
            snippet="片段", score=2,
        )]
        fallback = AsyncMock(return_value=expected)

        with patch(
            "app.rag.hybrid_retrieval.embed",
            AsyncMock(side_effect=RuntimeError("model down")),
        ), patch(
            "app.rag.hybrid_retrieval.knowledge_retrieval.search",
            fallback,
        ):
            hits = await search(object(), "user-1", "FastAPI")

        self.assertEqual(hits, expected)
        fallback.assert_awaited_once()

    async def test_graph_failure_falls_back_to_mysql(self):
        expected = [RetrievalHit(
            source_kind="note", source_id="note-1", title="标题",
            snippet="片段", score=1,
        )]
        fallback = AsyncMock(return_value=expected)

        with patch(
            "app.rag.hybrid_retrieval.embed",
            AsyncMock(return_value=[0.1]),
        ), patch(
            "app.rag.hybrid_retrieval.graph_driver",
            side_effect=RuntimeError("neo4j down"),
        ), patch(
            "app.rag.hybrid_retrieval.knowledge_retrieval.search",
            fallback,
        ):
            hits = await search(object(), "user-1", "FastAPI")

        self.assertEqual(hits, expected)
        fallback.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
