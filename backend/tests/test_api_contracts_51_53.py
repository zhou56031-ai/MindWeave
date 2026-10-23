"""第 51–53 章新增 HTTP 与 Compose 契约。"""

import unittest

from main import app


class RouteContractTests(unittest.TestCase):
    def test_new_routes_are_registered(self):
        routes = {
            (route.path, method)
            for route in app.routes
            for method in (getattr(route, "methods", None) or [])
        }
        self.assertIn(("/note/assist/stream", "POST"), routes)
        self.assertIn(("/note/{note_id}/related", "GET"), routes)
        self.assertIn(("/chat/reorder", "POST"), routes)
        self.assertIn(("/api/graph/notes/{note_id}/re-extract", "POST"), routes)
        self.assertIn(("/chat/session/{session_id}/approval", "GET"), routes)


if __name__ == "__main__":
    unittest.main()
