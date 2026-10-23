"""Final acceptance checks that do not require external services."""

import unittest

from fastapi.testclient import TestClient

from main import app


class AcceptanceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.routes = {
            (route.path, method)
            for route in app.routes
            for method in (getattr(route, "methods", None) or [])
        }

    def test_health_security_and_docs_routes(self):
        expected = {
            ("/health/live", "GET"),
            ("/health/ready", "GET"),
            ("/openapi.json", "GET"),
            ("/user/login/", "POST"),
            ("/user/refresh-token/", "POST"),
        }
        self.assertLessEqual(expected, self.routes)

    def test_agent_approval_and_graph_rebuild_routes(self):
        expected = {
            ("/chat/agent/resume", "POST"),
            ("/chat/session/{session_id}/approval", "GET"),
            ("/api/graph/notes/{note_id}/re-extract", "POST"),
        }
        self.assertLessEqual(expected, self.routes)

    def test_media_mount_and_process_time_header(self):
        names = {getattr(route, "name", "") for route in app.routes}
        self.assertIn("media", names)
        client = TestClient(app)
        try:
            response = client.get("/health/live")
        finally:
            client.close()
        self.assertEqual(response.status_code, 200)
        self.assertIn("X-Process-Time", response.headers)
        self.assertGreaterEqual(float(response.headers["X-Process-Time"]), 0)


if __name__ == "__main__":
    unittest.main()
