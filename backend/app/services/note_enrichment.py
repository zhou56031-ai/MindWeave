"""笔记保存后的异步标签与分类，不占用请求事务。"""

import json
from pathlib import Path

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select, update

from app.db.db_config import AsyncSessionLocal
from app.models.note import Note
from app.services.deepseek_client import deepseek_client

PROMPT = Path(__file__).resolve().parents[1] / "prompt" / "auto_tag_category.txt"


class NoteMetadata(BaseModel):
    tags: list[str] = Field(min_length=1, max_length=5)
    category: str = Field(pattern=r"^(work|study|life|project)$")

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(
            value.strip() for value in values if value.strip()
        ))
        if not cleaned or any(len(value) > 50 for value in cleaned):
            raise ValueError("标签为空或过长")
        return cleaned


async def enrich_note(note_id: str, user_id: str) -> None:
    async with AsyncSessionLocal() as db:
        note = await db.scalar(select(Note).where(
            Note.id == note_id,
            Note.user_id == user_id,
        ))
        if note is None:
            return
        text = (note.title + "\n" + note.content)[:4000]

    try:
        raw = await deepseek_client.chat([
            {"role": "system", "content": PROMPT.read_text(encoding="utf-8")},
            {"role": "user", "content": text},
        ], json_mode=True, max_tokens=180)
        payload = NoteMetadata.model_validate(json.loads(raw))
    except Exception:
        return

    async with AsyncSessionLocal() as db:
        # 模型等待期间，用户可能已经手动填写；只填空字段。
        await db.execute(update(Note).where(
            Note.id == note_id,
            Note.user_id == user_id,
            or_(
                Note.tags.is_(None),
                func.json_type(Note.tags) == "NULL",
            ),
            Note.category.is_(None),
        ).values(tags=payload.tags, category=payload.category))
        await db.commit()
