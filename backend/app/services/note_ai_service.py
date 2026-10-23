"""笔记 AI 辅助：补全只给建议，标签经过校验后持久化。"""

import json

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.note import Note
from app.schemas.models import AutoTagResponse, AutocompleteResponse
from app.services.deepseek_client import deepseek_client


class TagPayload(BaseModel):
    tags: list[str] = Field(min_length=1, max_length=5)

    @field_validator("tags")
    @classmethod
    def valid_tags(cls, tags: list[str]) -> list[str]:
        cleaned = [tag.strip() for tag in tags]
        if any(not tag or len(tag) > 50 for tag in cleaned) or len(set(cleaned)) != len(cleaned):
            raise ValueError("标签需要非空、唯一且不超过 50 字符")
        return cleaned


class NoteAIService:
    async def assist_chunks(self, content: str, action: str):
        tasks = {
            "continue": "沿原文续写一小段，保持语气，不重复原文",
            "expand": "扩写原文，补充解释，不捏造事实",
            "summarize": "把原文缩写成更短的一段，保留关键意思",
        }
        instruction = tasks[action]
        async for part in deepseek_client.stream_chat([
            {
                "role": "system",
                "content": (
                    "你是笔记写作助手。只输出建议文本；不得宣称已保存笔记。"
                    + instruction
                ),
            },
            {"role": "user", "content": content[:6000]},
        ], max_tokens=650):
            yield part

    async def autocomplete(self, context: str) -> AutocompleteResponse:
        result = await deepseek_client.chat([
            {"role": "system", "content": "只续写用户编辑器光标前的文字，返回一句简短续写，不要重复原文。"},
            {"role": "user", "content": context[-2000:]},
        ], max_tokens=80)
        return AutocompleteResponse(completion=result[:300])

    async def auto_tag(
        self, db: AsyncSession, user_id: str, note_id: str
    ) -> AutoTagResponse:
        note = await db.scalar(select(Note).where(Note.id == note_id, Note.user_id == user_id))
        if note is None:
            raise HTTPException(status_code=404, detail="笔记不存在")
        note_text = (note.title + "\n" + note.content)[:3000]
        # 远程模型等待期间释放只读事务和连接；稍后写入时重新确认所有权。
        await db.rollback()
        raw = await deepseek_client.chat([
            {"role": "system", "content": "为笔记提取 1 到 5 个标签。只返回 JSON，例如 {\"tags\":[\"Python\",\"后端\"]}。"},
            {"role": "user", "content": note_text},
        ], json_mode=True, max_tokens=180)
        try:
            tags = TagPayload.model_validate(json.loads(raw)).tags
        except (ValueError, ValidationError) as exc:
            raise HTTPException(status_code=502, detail="模型标签格式异常") from exc
        note = await db.scalar(select(Note).where(Note.id == note_id, Note.user_id == user_id))
        if note is None:
            raise HTTPException(status_code=404, detail="笔记不存在")
        note.tags = tags
        await db.commit()
        return AutoTagResponse(note_id=note.id, tags=tags)


note_ai_service = NoteAIService()
