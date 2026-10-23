"""父子块：同章节合并、跨章节切组、超长强制切组。"""
import unittest

from app.rag.evidence_selection import expand_neighbors
from app.schemas.models import RetrievalHit
from app.services.structured_chunks import IndexPiece, parent_map


class ParentMapTests(unittest.TestCase):
    def test_same_section_shares_parent(self):
        pieces = [IndexPiece("a" * 300, 1, "第一章"), IndexPiece("b" * 300, 1, "第一章")]
        mapping = parent_map(pieces)
        self.assertEqual(mapping[0], mapping[1])
        self.assertIn("a" * 20, mapping[0][1])

    def test_section_change_starts_new_parent(self):
        pieces = [IndexPiece("a" * 100, 1, "第一章"), IndexPiece("b" * 100, 2, "第二章")]
        mapping = parent_map(pieces)
        self.assertNotEqual(mapping[0][0], mapping[1][0])

    def test_limit_forces_new_parent(self):
        pieces = [IndexPiece("a" * 900, 1, "第一章"), IndexPiece("b" * 900, 1, "第一章")]
        mapping = parent_map(pieces, limit=1000)
        self.assertNotEqual(mapping[0][0], mapping[1][0])

    def test_empty(self):
        self.assertEqual(parent_map([]), [])


class ParentEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_parent_text_short_circuits_neighbor_expansion(self):
        hit = RetrievalHit(
            source_kind="knowledge_base", source_id="d1", title="文档",
            snippet="子块", parent_text="父块全文", score=10, chunk_id="c1",
        )
        expanded = await expand_neighbors("u1", hit)
        self.assertEqual(expanded.snippet, "父块全文")
        self.assertEqual(expanded.chunk_id, "c1")


if __name__ == "__main__":
    unittest.main()
