"""语义笔记搜索的排序、分页和空结果。"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.rag.note_search import semantic_note_search


class SemanticNoteSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_preserves_hit_order_and_filters_missing_notes(self):
        hits = [
            SimpleNamespace(source_kind="note", source_id="n2"),
            SimpleNamespace(source_kind="knowledge_base", source_id="d1"),
            SimpleNamespace(source_kind="note", source_id="missing"),
            SimpleNamespace(source_kind="note", source_id="n1"),
        ]
        notes = [
            SimpleNamespace(id="n1", title="一"),
            SimpleNamespace(id="n2", title="二"),
        ]
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: notes),
        )))

        with patch("app.rag.note_search.search", AsyncMock(return_value=hits)):
            ordered, total = await semantic_note_search(
                db, "user-1", "查询", page=1, page_size=20,
            )

        self.assertEqual([note.id for note in ordered], ["n2", "n1"])
        self.assertEqual(total, 2)

    async def test_empty_hits_do_not_query_mysql(self):
        db = SimpleNamespace(execute=AsyncMock())
        with patch("app.rag.note_search.search", AsyncMock(return_value=[])):
            notes, total = await semantic_note_search(db, "user-1", "查询")

        self.assertEqual(notes, [])
        self.assertEqual(total, 0)
        db.execute.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
