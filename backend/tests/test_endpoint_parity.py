"""Frontend endpoints must map to real FastAPI routes."""

import unittest

from main import app


EXPECTED_ROUTES = {
    # Auth, profile, and avatar
    ("/user/login/", "POST"),
    ("/user/logout/", "POST"),
    ("/user/register/", "POST"),
    ("/user/refresh-token/", "POST"),
    ("/user/detail/", "GET"),
    ("/user/update/", "PUT"),
    ("/user/reset-password/", "POST"),
    ("/file/upload/", "POST"),
    # Notes
    ("/note/create", "POST"),
    ("/note/list", "GET"),
    ("/note/search", "GET"),
    ("/note/stats", "GET"),
    ("/note/{note_id}", "GET"),
    ("/note/{note_id}", "PUT"),
    ("/note/{note_id}", "DELETE"),
    ("/note/{note_id}/pin", "PUT"),
    ("/note/{note_id}/related", "GET"),
    ("/note/{note_id}/download", "GET"),
    ("/note/{note_id}/export", "GET"),
    ("/note/{note_id}/auto-tag", "POST"),
    ("/note/autocomplete", "POST"),
    ("/note/assist/stream", "POST"),
    ("/note/batch/delete", "POST"),
    ("/note/batch/download", "POST"),
    ("/note/batch/category", "PUT"),
    ("/note/batch/pin", "PUT"),
    ("/note/category/{category}", "DELETE"),
    # Chat, knowledge, and graph
    ("/chat/agent/query/stream", "POST"),
    ("/chat/agent/resume", "POST"),
    ("/chat/reorder", "POST"),
    ("/chat/sessions", "GET"),
    ("/chat/sessions/{path_user_id}", "GET"),
    ("/chat/session/{session_id}", "GET"),
    ("/chat/session/{session_id}", "DELETE"),
    ("/chat/session/{session_id}/pending", "GET"),
    ("/chat/session/{session_id}/approval", "GET"),
    ("/knowledge/add/single", "POST"),
    ("/knowledge/add/multiple", "POST"),
    ("/knowledge/add/multiple/stream", "POST"),
    ("/knowledge/list", "GET"),
    ("/knowledge/detail", "GET"),
    ("/knowledge/chunks", "GET"),
    ("/knowledge/clean", "DELETE"),
    ("/knowledge/delete/filename", "DELETE"),
    ("/knowledge/image/{md5_value}/{filename}", "GET"),
    ("/knowledge/images/all/{md5_value}", "GET"),
    ("/knowledge/md5/list", "GET"),
    ("/knowledge/md5/{md5_value}", "GET"),
    ("/knowledge/md5/delete/{md5_value}", "DELETE"),
    ("/knowledge/md5/clear", "DELETE"),
    ("/api/graph/overview", "GET"),
    ("/api/graph/events", "GET"),
    ("/api/graph/extract-logs", "GET"),
    ("/api/graph/entity/{entity_id}", "GET"),
    ("/api/graph/entity/{entity_id}/neighbors", "GET"),
    ("/api/graph/entity/{entity_id}/notes", "GET"),
    ("/api/graph/notes/{note_id}/related", "GET"),
    ("/api/graph/notes/{note_id}/re-extract", "POST"),
    ("/api/graph/docs/{doc_id}/related", "GET"),
    ("/api/graph/search", "GET"),
    ("/api/graph/entities", "POST"),
    ("/api/graph/entities/{entity_id}", "PUT"),
    ("/api/graph/entities/{entity_id}", "DELETE"),
    ("/api/graph/entities/merge", "POST"),
    ("/api/graph/types", "GET"),
    ("/api/graph/types", "POST"),
    ("/api/graph/types/{type_id}", "PUT"),
    ("/api/graph/types/{type_id}", "DELETE"),
    ("/api/graph/relations", "POST"),
    ("/api/graph/relations/{relation_id}", "DELETE"),
    # Review and templates
    ("/review/today", "GET"),
    ("/review/done/{note_id}", "POST"),
    ("/review/question/{note_id}", "GET"),
    ("/note-template/list", "GET"),
    ("/note-template/create", "POST"),
    ("/note-template/reorder", "PUT"),
    ("/note-template/{template_id}", "PUT"),
    ("/note-template/{template_id}", "DELETE"),
}


class EndpointParityTests(unittest.TestCase):
    def test_every_frontend_endpoint_has_matching_method(self):
        routes = {
            (route.path, method)
            for route in app.routes
            for method in (getattr(route, "methods", None) or [])
        }
        self.assertLessEqual(EXPECTED_ROUTES, routes)


if __name__ == "__main__":
    unittest.main()
