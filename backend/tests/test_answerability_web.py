"""可答性规则、模型校验与 Web 搜索客户端。"""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.rag.answerability import Answerability, evaluate
from app.rag.web_search import search_web
from app.schemas.models import RetrievalHit


def hit() -> RetrievalHit:
    return RetrievalHit(
        source_kind="note", source_id="n1", title="资料",
        snippet="FastAPI 使用 Python", score=1,
    )


class AnswerabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_evidence_requires_web(self):
        result = await evaluate("FastAPI 是什么", [])
        self.assertFalse(result.answerable)
        self.assertTrue(result.web_queries)

    async def test_freshness_requires_web_even_with_local_hits(self):
        result = await evaluate("FastAPI 最新版本", [hit()])
        self.assertFalse(result.answerable)
        self.assertTrue(result.web_queries)

    async def test_model_result_is_validated(self):
        with patch(
            "app.rag.answerability.deepseek_client.chat",
            AsyncMock(return_value=json.dumps({
                "answerable": True,
                "confidence": 0.8,
                "reason": "证据足够",
                "web_queries": [],
            })),
        ):
            result = await evaluate("FastAPI 使用什么语言", [hit()])
        self.assertTrue(result.answerable)
        self.assertEqual(result.confidence, 0.8)


class WebSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_search_returns_empty(self):
        with patch("app.rag.web_search._enabled", return_value=False):
            self.assertEqual(await search_web("FastAPI"), [])

    async def test_tavily_rows_become_web_evidence(self):
        response = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"results": [{
                "title": "FastAPI", "url": "https://example.com",
                "content": "ASGI framework",
            }]},
        )
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        context = AsyncMock()
        context.__aenter__.return_value = client
        context.__aexit__.return_value = False
        with patch("app.rag.web_search._enabled", return_value=True), \
             patch("app.rag.web_search.settings.WEB_SEARCH_PROVIDER", "tavily"), \
             patch("app.rag.web_search.settings.WEB_SEARCH_API_KEY",
                   SimpleNamespace(get_secret_value=lambda: "key")), \
             patch("app.rag.web_search.httpx.AsyncClient", return_value=context):
            hits = await search_web("FastAPI")

        self.assertEqual(hits[0].source_kind, "web")
        self.assertEqual(hits[0].title, "FastAPI")


if __name__ == "__main__":
    unittest.main()
