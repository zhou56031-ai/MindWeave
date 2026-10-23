"""第 40 篇实体关系结构与模型边界回归。"""

import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.graph.extractor import extract_entities
from app.graph.schemas import ExtractResult


class ExtractResultTests(unittest.TestCase):
    def test_accepts_relations_between_declared_entities(self):
        result = ExtractResult.model_validate({
            "entities": [{"name": "FastAPI"}, {"name": "Python"}],
            "relations": [{
                "source": "FastAPI",
                "target": "Python",
                "relation_type": "uses",
            }],
        })

        self.assertEqual(len(result.entities), 2)
        self.assertEqual(result.relations[0].relation_type, "uses")

    def test_rejects_dangling_relation(self):
        with self.assertRaises(ValidationError):
            ExtractResult.model_validate({
                "entities": [{"name": "FastAPI"}],
                "relations": [{
                    "source": "FastAPI",
                    "target": "Missing",
                    "relation_type": "uses",
                }],
            })

    def test_rejects_names_that_share_graph_id(self):
        with self.assertRaises(ValidationError):
            ExtractResult.model_validate({
                "entities": [{"name": "FastAPI"}, {"name": "fastapi"}],
                "relations": [],
            })


class ExtractEntitiesTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_text_does_not_call_model(self):
        chat = AsyncMock()
        with patch("app.graph.extractor.deepseek_client.chat", chat):
            result = await extract_entities("   ")

        self.assertEqual(result.entities, [])
        chat.assert_not_awaited()

    async def test_truncates_source_and_validates_model_json(self):
        payload = {
            "entities": [{"name": "FastAPI"}, {"name": "Python"}],
            "relations": [{
                "source": "FastAPI",
                "target": "Python",
                "relation_type": "uses",
            }],
        }
        chat = AsyncMock(return_value=json.dumps(payload))
        with patch("app.graph.extractor.deepseek_client.chat", chat):
            result = await extract_entities("x" * 7000)

        self.assertEqual(result.relations[0].target, "Python")
        self.assertEqual(chat.await_args.args[0][1]["content"], "x" * 6000)
        self.assertTrue(chat.await_args.kwargs["json_mode"])

    async def test_invalid_model_output_becomes_bad_gateway(self):
        chat = AsyncMock(return_value='{"foo": 1}')
        with patch("app.graph.extractor.deepseek_client.chat", chat):
            with self.assertRaises(HTTPException) as raised:
                await extract_entities("A uses B")

        self.assertEqual(raised.exception.status_code, 502)

    async def test_dangling_relation_is_dropped_instead_of_failing(self):
        chat = AsyncMock(return_value='{"entities": [{"name": "A"}], '
                                      '"relations": [{"source": "A", '
                                      '"target": "B", "relation_type": "uses"}]}')
        with patch("app.graph.extractor.deepseek_client.chat", chat):
            result = await extract_entities("A uses B")

        self.assertEqual([entity.name for entity in result.entities], ["A"])
        self.assertEqual(result.relations, [])


if __name__ == "__main__":
    unittest.main()
