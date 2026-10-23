"""PDF 页面渲染、感知哈希去重和视觉批处理。"""

import asyncio
import base64
import json
import re
from io import BytesIO

import imagehash
import pymupdf
from PIL import Image

from app.core.settings import REBUILD_ROOT, settings
from app.services.deepseek_client import deepseek_client

ASSET_ROOT = REBUILD_ROOT / "data" / "extracted_images"


def _image_path(user_id: str, md5_value: str, filename: str):
    return ASSET_ROOT / user_id / md5_value / filename


def _phash(png: bytes):
    return imagehash.phash(Image.open(BytesIO(png)))


def _parse_batch_result(raw: str) -> dict:
    stripped = raw.strip()
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.I)
    stripped = re.sub(r"\s*```$", "", stripped)
    match = re.search(r"\{.*\}", stripped, flags=re.S)
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


async def describe_pages(
    raw: bytes,
    user_id: str,
    md5_value: str,
    page_numbers: list[int],
) -> tuple[dict[int, str], dict[int, list[str]]]:
    rendered = []
    with pymupdf.open(stream=raw, filetype="pdf") as pdf:
        for number in page_numbers[:settings.VISION_MAX_PAGES]:
            page = pdf[number - 1]
            png = page.get_pixmap(matrix=pymupdf.Matrix(1.3, 1.3)).tobytes("png")
            path = _image_path(user_id, md5_value, f"page-{number}.png")
            path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(path.write_bytes, png)
            rendered.append((number, png, _phash(png)))

    representatives = []
    duplicate_of: dict[int, int] = {}
    for number, png, fingerprint in rendered:
        duplicate = None
        if settings.VISION_DEDUP_ENABLED:
            duplicate = next(
                (
                    rep for rep in representatives
                    if rep[2] - fingerprint <= settings.VISION_DEDUP_THRESHOLD
                ),
                None,
            )
        if duplicate is None:
            representatives.append((number, png, fingerprint))
        else:
            duplicate_of[number] = duplicate[0]

    descriptions: dict[int, str] = {}
    for start in range(0, len(representatives), settings.VISION_BATCH_SIZE):
        batch = representatives[start:start + settings.VISION_BATCH_SIZE]
        content = [{
            "type": "text",
            "text": (
                "客观描述这些学习资料页面中的可见文字、表格和图。"
                "按页码返回 JSON 对象，键是页码字符串，值是描述。"
                f"页码：{[item[0] for item in batch]}"
            ),
        }]
        for _, png, _ in batch:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": "data:image/png;base64,"
                    + base64.b64encode(png).decode("ascii"),
                    "detail": "low",
                },
            })
        raw_result = await deepseek_client.chat(
            [{"role": "user", "content": content}],
            max_tokens=800,
        )
        result = _parse_batch_result(raw_result)
        for number, _, _ in batch:
            descriptions[number] = str(result.get(str(number), ""))

    for number, representative in duplicate_of.items():
        descriptions[number] = descriptions.get(representative, "")
    images = {
        number: [f"/knowledge/image/{md5_value}/page-{number}.png"]
        for number, _, _ in rendered
    }
    return descriptions, images
