"""PDF 视觉增强与用户范围内图片路径。"""

import re
import shutil
from pathlib import Path

import pymupdf
from fastapi import HTTPException

from app.core.settings import REBUILD_ROOT
from app.services.vision_pages import describe_pages

ASSET_ROOT = REBUILD_ROOT / "data" / "extracted_images"
PAGE_NAME = re.compile(r"page-[1-9][0-9]*\.png")


def image_path(user_id: str, md5_value: str, filename: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", md5_value) or not PAGE_NAME.fullmatch(filename):
        raise HTTPException(status_code=404, detail="图片不存在")
    return ASSET_ROOT / user_id / md5_value / filename


def remove_images(user_id: str, md5_value: str) -> None:
    shutil.rmtree(ASSET_ROOT / user_id / md5_value, ignore_errors=True)


async def enrich_pdf(
    raw: bytes,
    user_id: str,
    md5_value: str,
    pages: list[tuple[int | None, str]],
) -> tuple[list[tuple[int | None, str]], dict[int, list[str]]]:
    text_by_page = {number: text for number, text in pages if number is not None}
    vision_pages: list[int] = []
    with pymupdf.open(stream=raw, filetype="pdf") as pdf:
        for index, page in enumerate(pdf):
            number = index + 1
            text = text_by_page.get(number, "")
            needs_vision = len(text) < 100 or bool(page.get_images())
            if needs_vision:
                vision_pages.append(number)

    descriptions: dict[int, str] = {}
    image_urls: dict[int, list[str]] = {}
    if vision_pages:
        try:
            descriptions, image_urls = await describe_pages(
                raw, user_id, md5_value, vision_pages,
            )
        except Exception:
            descriptions = {}
            image_urls = {}

    output: list[tuple[int | None, str]] = []
    for number, text in text_by_page.items():
        description = descriptions.get(number, "")
        combined = (text + "\n" + description).strip()
        if combined:
            output.append((number, combined))
    if not output:
        raise HTTPException(status_code=422, detail="PDF 没有可读取内容")
    return output, image_urls
