"""双链解析和 Chunk 提及规则。"""

import unittest

from app.graph.link_parser import parse_links


class LinkParserTests(unittest.TestCase):
    def test_extracts_unique_titles_in_order(self):
        content = "参考 [[FastAPI]] 和 [[数据库]]，再回到 [[FastAPI]]。"
        self.assertEqual(parse_links(content), ["FastAPI", "数据库"])

    def test_ignores_unclosed_or_empty_links(self):
        self.assertEqual(parse_links("[[ ]] [[未闭合"), [])


if __name__ == "__main__":
    unittest.main()
