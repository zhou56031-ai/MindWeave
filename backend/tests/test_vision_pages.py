"""PDF visual batching, duplicate reuse, and image lifecycle."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import imagehash
import pymupdf

from app.router.knowledge_router import get_all_document_images
from app.services import vision_pages
from app.services.pdf_vision import remove_images


def make_pdf(page_count: int) -> bytes:
    document = pymupdf.open()
    try:
        for index in range(page_count):
            page = document.new_page()
            page.insert_text((72, 72), f"page {index + 1}")
        return document.tobytes()
    finally:
        document.close()


class VisionPageTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_pages_reuse_representative_description(self):
        first = imagehash.hex_to_hash("0000000000000000")
        second = imagehash.hex_to_hash("ffffffffffffffff")
        chat = AsyncMock(return_value='{"1":"same","3":"other"}')
        with tempfile.TemporaryDirectory() as temp:
            with (
                patch.object(vision_pages, "ASSET_ROOT", Path(temp)),
                patch.object(vision_pages, "_phash", side_effect=[
                    first, first, second, second,
                ]),
                patch.object(vision_pages.settings, "VISION_DEDUP_ENABLED", True),
                patch.object(vision_pages.settings, "VISION_DEDUP_THRESHOLD", 0),
                patch.object(vision_pages.settings, "VISION_BATCH_SIZE", 5),
                patch.object(vision_pages.deepseek_client, "chat", chat),
            ):
                descriptions, images = await vision_pages.describe_pages(
                    make_pdf(4), "user-1", "a" * 32, [1, 2, 3, 4],
                )

        self.assertEqual(chat.await_count, 1)
        self.assertEqual(descriptions[1], "same")
        self.assertEqual(descriptions[2], "same")
        self.assertEqual(descriptions[3], "other")
        self.assertEqual(descriptions[4], "other")
        self.assertEqual(len(images), 4)

    async def test_representatives_are_sent_in_configured_batches(self):
        fingerprints = [
            imagehash.hex_to_hash(f"{index:016x}")
            for index in range(1, 7)
        ]
        chat = AsyncMock(return_value="{}")
        with tempfile.TemporaryDirectory() as temp:
            with (
                patch.object(vision_pages, "ASSET_ROOT", Path(temp)),
                patch.object(vision_pages, "_phash", side_effect=fingerprints),
                patch.object(vision_pages.settings, "VISION_DEDUP_ENABLED", True),
                patch.object(vision_pages.settings, "VISION_DEDUP_THRESHOLD", 0),
                patch.object(vision_pages.settings, "VISION_BATCH_SIZE", 2),
                patch.object(vision_pages.deepseek_client, "chat", chat),
            ):
                await vision_pages.describe_pages(
                    make_pdf(6), "user-1", "b" * 32, [1, 2, 3, 4, 5, 6],
                )
        self.assertEqual(chat.await_count, 3)

    def test_invalid_batch_json_becomes_empty_description(self):
        self.assertEqual(vision_pages._parse_batch_result("not json"), {})
        self.assertEqual(
            vision_pages._parse_batch_result('```json\n{"1":"ok"}\n```'),
            {"1": "ok"},
        )


class ImageLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_images_are_owned_and_naturally_ordered(self):
        class DB:
            async def scalar(self, _statement):
                return "document-id"

        md5_value = "c" * 32
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "user-1" / md5_value
            root.mkdir(parents=True)
            for number in (10, 2, 1):
                (root / f"page-{number}.png").write_bytes(b"png")
            with patch("app.services.pdf_vision.ASSET_ROOT", Path(temp)):
                response = await get_all_document_images(
                    md5_value, "user-1", DB(),
                )

        payload = json.loads(response.body)
        filenames = [
            item["filename"] for item in payload["data"]["images"]
        ]
        self.assertEqual(filenames, ["page-1.png", "page-2.png", "page-10.png"])

    def test_remove_images_deletes_only_requested_document(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "user-1" / ("d" * 32)
            other = Path(temp) / "user-1" / ("e" * 32)
            target.mkdir(parents=True)
            other.mkdir(parents=True)
            (target / "page-1.png").write_bytes(b"png")
            (other / "page-1.png").write_bytes(b"png")
            with patch("app.services.pdf_vision.ASSET_ROOT", Path(temp)):
                remove_images("user-1", "d" * 32)
            self.assertFalse(target.exists())
            self.assertTrue(other.exists())


if __name__ == "__main__":
    unittest.main()
