"""自动标签与分类的后台写回。"""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services import note_enrichment


class FakeContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class NoteEnrichmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_validates_and_updates_blank_metadata(self):
        first = SimpleNamespace(scalar=AsyncMock(return_value=SimpleNamespace(
            title="FastAPI 笔记", content="依赖注入和数据库会话",
        )))
        execute = AsyncMock()
        second = SimpleNamespace(execute=execute, commit=AsyncMock())
        chat = AsyncMock(return_value=json.dumps({
            "tags": ["FastAPI", "数据库"],
            "category": "study",
        }))

        with patch(
            "app.services.note_enrichment.AsyncSessionLocal",
            side_effect=[FakeContext(first), FakeContext(second)],
        ), patch("app.services.note_enrichment.deepseek_client.chat", chat):
            await note_enrichment.enrich_note("note-1", "user-1")

        execute.assert_awaited_once()
        second.commit.assert_awaited_once()

    async def test_invalid_model_output_is_ignored(self):
        first = SimpleNamespace(scalar=AsyncMock(return_value=SimpleNamespace(
            title="标题", content="正文",
        )))
        second = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())

        with patch(
            "app.services.note_enrichment.AsyncSessionLocal",
            side_effect=[FakeContext(first), FakeContext(second)],
        ), patch(
            "app.services.note_enrichment.deepseek_client.chat",
            AsyncMock(return_value='{"tags":[],"category":"other"}'),
        ):
            await note_enrichment.enrich_note("note-1", "user-1")

        second.execute.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
