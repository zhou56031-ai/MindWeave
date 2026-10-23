"""第 42 篇图谱任务登记回归。"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from app.graph.task_queue import enqueue_graph
from app.models.graph_task import GraphTask


class GraphQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_pending_task(self):
        db = SimpleNamespace(scalar=AsyncMock(return_value=None), add=Mock())
        user_id = str(uuid4())
        source_id = str(uuid4())

        await enqueue_graph(db, user_id, "note", source_id)

        task = db.add.call_args.args[0]
        self.assertIsInstance(task, GraphTask)
        self.assertEqual(task.user_id, user_id)
        self.assertEqual(task.source_kind, "note")
        self.assertEqual(task.source_id, source_id)
        self.assertEqual(task.status, "pending")

    async def test_reuses_existing_task_and_clears_attempt_state(self):
        existing = SimpleNamespace(
            status="failed", attempts=3, run_token="old-token",
            error_message="old error",
        )
        db = SimpleNamespace(scalar=AsyncMock(return_value=existing), add=Mock())

        await enqueue_graph(db, str(uuid4()), "doc", str(uuid4()))

        self.assertEqual(existing.status, "pending")
        self.assertEqual(existing.attempts, 0)
        self.assertIsNone(existing.run_token)
        self.assertIsNone(existing.error_message)
        db.add.assert_not_called()

    async def test_rejects_unknown_source_kind(self):
        db = SimpleNamespace(scalar=AsyncMock(), add=Mock())

        with self.assertRaises(ValueError):
            await enqueue_graph(db, str(uuid4()), "chunk", str(uuid4()))

        db.scalar.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
