"""Rate limiting, warmup, avatar, and graph maintenance contracts."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException

from app.core.rate_limit import rate_limit
from app.core.warmup import warm_embedding
from app.graph.maintenance import ensure_system_types
from app.graph.task_queue import enqueue_graph
from app.router.file_router import upload_avatar


class RateLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_over_limit_returns_429(self):
        request = SimpleNamespace(
            client=SimpleNamespace(host="127.0.0.1"),
            headers={},
        )
        redis = SimpleNamespace(
            incr=AsyncMock(return_value=3),
            expire=AsyncMock(),
        )
        with (
            patch("app.core.rate_limit.settings.RATE_LIMIT_ENABLED", True),
            patch("app.core.rate_limit.get_redis", return_value=redis),
        ):
            dependency = rate_limit("chat", 2)
            with self.assertRaises(HTTPException) as raised:
                await dependency(request)

        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(raised.exception.headers["Retry-After"], "60")

    async def test_disabled_limit_does_not_touch_redis(self):
        redis_factory = Mock()
        with (
            patch("app.core.rate_limit.settings.RATE_LIMIT_ENABLED", False),
            patch("app.core.rate_limit.get_redis", redis_factory),
        ):
            await rate_limit("chat", 1)(SimpleNamespace(client=None))
        redis_factory.assert_not_called()

    async def test_redis_failure_returns_503(self):
        request = SimpleNamespace(
            client=SimpleNamespace(host="127.0.0.1"),
            headers={},
        )
        redis = SimpleNamespace(incr=AsyncMock(side_effect=ConnectionError("down")))
        with (
            patch("app.core.rate_limit.settings.RATE_LIMIT_ENABLED", True),
            patch("app.core.rate_limit.get_redis", return_value=redis),
        ):
            with self.assertRaises(HTTPException) as raised:
                await rate_limit("chat", 2)(request)
        self.assertEqual(raised.exception.status_code, 503)

    async def test_valid_proxy_client_ip_is_used_in_key(self):
        request = SimpleNamespace(
            client=SimpleNamespace(host="172.18.0.5"),
            headers={"x-real-ip": "203.0.113.9"},
        )
        redis = SimpleNamespace(incr=AsyncMock(return_value=1), expire=AsyncMock())
        with (
            patch("app.core.rate_limit.settings.RATE_LIMIT_ENABLED", True),
            patch("app.core.rate_limit.get_redis", return_value=redis),
        ):
            await rate_limit("chat", 2)(request)
        key = redis.incr.await_args.args[0]
        self.assertIn(":203.0.113.9:", key)


class WarmupTests(unittest.IsolatedAsyncioTestCase):
    async def test_warmup_failure_is_isolated(self):
        with patch(
            "app.core.warmup.embed",
            AsyncMock(side_effect=RuntimeError("model unavailable")),
        ):
            await warm_embedding()


class AvatarTests(unittest.IsolatedAsyncioTestCase):
    async def test_avatar_is_saved_and_owned_by_token_user(self):
        class Upload:
            filename = "avatar.png"

            async def read(self):
                return b"image-data"

        user = SimpleNamespace(avatar=None)
        db = SimpleNamespace(
            scalar=AsyncMock(return_value=user),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        with tempfile.TemporaryDirectory() as temp:
            with patch("app.router.file_router.MEDIA_ROOT", Path(temp)):
                result = await upload_avatar(Upload(), "user-1", db)
                target = Path(temp) / result["data"]["url"].removeprefix("/media/")
                self.assertTrue(target.is_file())
                self.assertEqual(target.read_bytes(), b"image-data")

        self.assertEqual(user.avatar, result["data"]["url"])

    async def test_failed_database_commit_removes_uploaded_file(self):
        class Upload:
            filename = "avatar.jpg"

            async def read(self):
                return b"image-data"

        user = SimpleNamespace(avatar=None)
        db = SimpleNamespace(
            scalar=AsyncMock(return_value=user),
            commit=AsyncMock(side_effect=RuntimeError("db down")),
            rollback=AsyncMock(),
        )
        with tempfile.TemporaryDirectory() as temp:
            with patch("app.router.file_router.MEDIA_ROOT", Path(temp)):
                with self.assertRaises(RuntimeError):
                    await upload_avatar(Upload(), "user-1", db)
                files = list(Path(temp).rglob("*"))
                self.assertEqual([path for path in files if path.is_file()], [])


class GraphMaintenanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_system_types_are_seeded_per_user(self):
        driver = SimpleNamespace(execute_query=AsyncMock(return_value=SimpleNamespace()))
        with patch(
            "app.graph.maintenance.graph_driver",
            return_value=driver,
        ):
            await ensure_system_types("user-1")
        self.assertEqual(driver.execute_query.await_count, 4)
        self.assertTrue(all(
            call.kwargs["uid"] == "user-1"
            for call in driver.execute_query.await_args_list
        ))
        query = driver.execute_query.await_args_list[0].args[0]
        self.assertLess(query.index("ON CREATE SET"), query.index("SET t.display_name"))

    async def test_enqueue_persists_snapshot_and_force(self):
        db = SimpleNamespace(scalar=AsyncMock(return_value=None), add=Mock())
        await enqueue_graph(
            db,
            "user-1",
            "doc",
            "doc-1",
            title="guide.pdf",
            content_hash="abc",
            payload={"chunks": [1, 2]},
            force=True,
        )
        task = db.add.call_args.args[0]
        self.assertEqual(task.title, "guide.pdf")
        self.assertEqual(task.content_hash, "abc")
        self.assertEqual(task.payload, '{"chunks": [1, 2]}')
        self.assertEqual(task.force, 1)


if __name__ == "__main__":
    unittest.main()
