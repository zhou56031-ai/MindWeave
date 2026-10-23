"""Local/remote embedding provider and dimension contracts."""

import unittest
from unittest.mock import AsyncMock, patch

from app.rag import embedding


class FakeModel:
    def __init__(self, dimensions: int):
        self.dimensions = dimensions

    def encode(self, texts: list[str], normalize_embeddings: bool):
        self.last_texts = texts
        self.normalized = normalize_embeddings
        return [[0.5] * self.dimensions for _ in texts]


class EmbeddingTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_provider_returns_configured_dimension(self):
        fake = FakeModel(512)
        with (
            patch.object(embedding.settings, "EMBEDDING_PROVIDER", "local"),
            patch("app.rag.embedding.model", return_value=fake),
        ):
            result = await embedding.embed("测试文字")

        self.assertEqual(len(result), 512)
        self.assertTrue(fake.normalized)
        self.assertEqual(fake.last_texts, ["测试文字"])

    async def test_remote_provider_batches_at_configured_size(self):
        remote = AsyncMock(side_effect=lambda texts: [
            [0.5] * 512 for _ in texts
        ])
        with (
            patch.object(embedding.settings, "EMBEDDING_PROVIDER", "remote"),
            patch.object(embedding.settings, "EMBEDDING_CACHE_ENABLED", False),
            patch.object(embedding.settings, "EMBEDDING_BATCH_SIZE", 2),
            patch("app.rag.embedding._remote_embeddings", remote),
        ):
            result = await embedding.embed_many(["a", "b", "c", "d", "e"])

        self.assertEqual(len(result), 5)
        self.assertEqual(remote.await_count, 3)
        self.assertEqual(
            [len(call.args[0]) for call in remote.await_args_list],
            [2, 2, 1],
        )

    async def test_rejects_model_dimension_mismatch(self):
        with (
            patch.object(embedding.settings, "EMBEDDING_PROVIDER", "local"),
            patch("app.rag.embedding.model", return_value=FakeModel(3)),
        ):
            with self.assertRaises(RuntimeError):
                await embedding.embed("测试文字")

    async def test_rejects_zero_vector(self):
        with self.assertRaises(RuntimeError):
            embedding._validate_vector([0.0] * 512)


if __name__ == "__main__":
    unittest.main()
