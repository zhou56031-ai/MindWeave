"""读取到期笔记、推进回顾进度，并生成回顾题。"""

import json
from datetime import timedelta
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.note import Note
from app.models.review_record import ReviewRecord
from app.schemas.models import (
    ReviewDoneResponse, ReviewItemResponse, ReviewQuestionResponse,
    ReviewTodayResponse,
)
from app.services.deepseek_client import deepseek_client
from app.services.review_schedule import interval_for_completed_count, utc_naive_now


class ReviewService:
    async def today(self, db: AsyncSession, user_id: str) -> ReviewTodayResponse:
        result = await db.execute(
            select(ReviewRecord, Note)
            .join(Note, ReviewRecord.note_id == Note.id)
            .where(
                ReviewRecord.user_id == user_id,
                Note.user_id == user_id,
                ReviewRecord.next_review_at <= utc_naive_now(),
            )
            .order_by(ReviewRecord.next_review_at.asc(), ReviewRecord.id.asc())
        )
        reviews = [ReviewItemResponse(
            review_id=record.id,
            note_id=note.id,
            title=note.title,
            content_preview=(note.content or "")[:200],
            tags=note.tags or [],
            category=note.category or "",
            review_count=record.review_count,
            last_reviewed_at=record.last_reviewed_at,
            interval_days=record.interval_days,
        ) for record, note in result.all()]
        return ReviewTodayResponse(reviews=reviews, total_count=len(reviews))

    async def mark_done(
        self, db: AsyncSession, user_id: str, note_id: str
    ) -> ReviewDoneResponse:
        result = await db.execute(
            select(ReviewRecord)
            .join(Note, ReviewRecord.note_id == Note.id)
            .where(
                ReviewRecord.note_id == note_id,
                ReviewRecord.user_id == user_id,
                Note.user_id == user_id,
            )
            .with_for_update()
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise HTTPException(status_code=404, detail="回顾记录不存在")
        now = utc_naive_now()
        if record.next_review_at > now:
            raise HTTPException(status_code=409, detail="尚未到回顾时间")

        record.review_count += 1
        record.interval_days = interval_for_completed_count(record.review_count)
        record.last_reviewed_at = now
        record.next_review_at = now + timedelta(days=record.interval_days)
        await db.commit()
        return ReviewDoneResponse(
            success=True,
            message="已标记回顾",
            review_count=record.review_count,
            interval_days=record.interval_days,
            next_review_at=record.next_review_at,
        )

    async def question(
        self, db: AsyncSession, user_id: str, note_id: str
    ) -> ReviewQuestionResponse:
        note = await db.scalar(select(Note).where(
            Note.id == note_id, Note.user_id == user_id,
        ))
        if note is None:
            raise HTTPException(status_code=404, detail="笔记不存在")

        # 【新增】先取出授权后的内容，再结束只读事务；模型等待期间不占用 MySQL 连接。
        note_content = (note.content or note.title)[:2000]
        await db.rollback()

        prompt_path = Path(__file__).resolve().parents[1] / "prompt" / "review_question.txt"
        system_prompt = prompt_path.read_text(encoding="utf-8")
        raw = await deepseek_client.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": note_content},
        ], json_mode=True, max_tokens=600)
        try:
            return ReviewQuestionResponse.model_validate(json.loads(raw))
        except (ValueError, ValidationError) as exc:
            raise HTTPException(status_code=502, detail="模型生成的题目不符合要求") from exc


review_service = ReviewService()
