"""融合与转义的单元测试：不依赖数据库。"""
import unittest

from app.rag.fusion import escape_lucene, fuse, rrf_points


def row(doc_id, text="x"):
    return {"id": doc_id, "text": text}


class FusionTests(unittest.TestCase):
    def test_rrf_points_monotonic(self):
        self.assertGreater(rrf_points(1), rrf_points(2))
        self.assertGreater(rrf_points(2), rrf_points(10))
        self.assertEqual(rrf_points(1), 100000 // 61)

    def test_fuse_merges_same_id_and_accumulates_score(self):
        ranked = fuse(
            [("vector", [row("a"), row("b")]), ("fulltext", [row("b"), row("c")])],
            limit=10,
        )
        by_id = {item[1]["id"]: item for item in ranked}
        self.assertEqual(by_id["b"][0], rrf_points(2) + rrf_points(1))
        self.assertEqual(by_id["b"][1]["sources"], ["vector", "fulltext"])
        self.assertGreater(by_id["b"][0], by_id["a"][0])

    def test_fuse_applies_per_source_quota_before_merge(self):
        ranked = fuse(
            [("vector", [row("v1"), row("v2"), row("v3")]), ("fulltext", [row("f1")])],
            limit=10,
            quotas={"vector": 1},
        )
        ids = [item[1]["id"] for item in ranked]
        self.assertNotIn("v2", ids)
        self.assertNotIn("v3", ids)
        self.assertEqual(ids, ["v1", "f1"])

    def test_fuse_respects_limit(self):
        ranked = fuse([("vector", [row(f"d{i}") for i in range(20)])], limit=5)
        self.assertEqual([item[1]["id"] for item in ranked], [f"d{i}" for i in range(5)])

    def test_escape_lucene_covers_special_characters(self):
        raw = 'a+b-c&&d||e!f(g)h{i}j[k]l^m"n~o*p?q:r\\s/t'
        escaped = escape_lucene(raw)
        for char in '+-&|!(){}[]^"~*?:\\/':
            self.assertIn(f"\\{char}", escaped)
        self.assertNotEqual(escape_lucene("缓存击穿"), "")


if __name__ == "__main__":
    unittest.main()
