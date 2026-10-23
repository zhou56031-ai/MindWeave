"""第 43、44 章路由和编辑输入契约。"""

import unittest
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from app.graph.edit_schemas import EntityIn, RelationIn, TypeIn
from app.graph.router import overview
from main import app


class GraphRouteTests(unittest.IsolatedAsyncioTestCase):
    def test_graph_routes_registered(self):
        routes = {
            (route.path, method)
            for route in app.routes
            for method in (getattr(route, "methods", None) or [])
        }
        expected = {
            ("/api/graph/overview", "GET"),
            ("/api/graph/events", "GET"),
            ("/api/graph/entities", "POST"),
            ("/api/graph/entities/{entity_id}", "PUT"),
            ("/api/graph/entities/{entity_id}", "DELETE"),
            ("/api/graph/entities/merge", "POST"),
            ("/api/graph/types", "GET"),
            ("/api/graph/types", "POST"),
            ("/api/graph/relations", "POST"),
        }
        self.assertLessEqual(expected, routes)

    async def test_overview_parses_type_filter(self):
        graph_view = AsyncMock(return_value={"nodes": [], "edges": []})
        with patch("app.graph.router.graph_view", graph_view):
            await overview(types="type-a, type-b", limit=10, user_id="user-1")

        graph_view.assert_awaited_once_with(
            "user-1", entity_types=["type-a", "type-b"], limit=10,
        )


class GraphEditSchemaTests(unittest.TestCase):
    def test_entity_normalizes_names_and_aliases(self):
        payload = EntityIn(
            name="  FastAPI  ",
            display_name="  Web 框架  ",
            aliases=[" Python ", "Python", "  ", "Web"],
        )

        self.assertEqual(payload.name, "FastAPI")
        self.assertEqual(payload.display_name, "Web 框架")
        self.assertEqual(payload.aliases, ["Python", "Web"])

    def test_type_rejects_invalid_color(self):
        with self.assertRaises(ValidationError):
            TypeIn(
                name="concept",
                display_name="概念",
                color="blue",
            )

    def test_relation_rejects_blank_type(self):
        with self.assertRaises(ValidationError):
            RelationIn(
                source_id="a",
                target_id="b",
                relation_type="   ",
            )


if __name__ == "__main__":
    unittest.main()
