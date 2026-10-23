import asyncio
from io import BytesIO
import json
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.failed_response import BusinessException
from app.graph.task_queue import enqueue_graph
from app.models.note import Note
from app.models.review_record import ReviewRecord
from app.rag.note_search import semantic_note_search
from app.schemas.models import NoteCreate, NoteUpdate
from app.services.note_enrichment import enrich_note
from app.services.review_schedule import first_due_at, utc_naive_now


class NoteService:
    async def create_note(
        self, db: AsyncSession, user_id: str, payload: NoteCreate
    ) -> Note:
        # 【新增】字段来源明确，归属取服务端依赖，不信任客户端 user_id。
        note = Note(
            id=str(uuid4()),
            user_id=user_id,
            title=payload.title,
            content=payload.content,
            tags=payload.tags,
            category=payload.category,
        )
        db.add(note)
        # 【新增】父笔记与回顾记录共用一次提交，避免只留下其中一行。
        await db.flush()
        now = utc_naive_now()
        db.add(ReviewRecord(
            id=str(uuid4()), note_id=note.id, user_id=user_id,
            next_review_at=first_due_at(now), interval_days=1,
            review_count=0,
        ))
        await enqueue_graph(db, user_id, "note", note.id)
        await db.commit()
        await db.refresh(note)
        if payload.tags is None and payload.category is None:
            asyncio.create_task(enrich_note(note.id, user_id))
        return note

    async def get_note(
        self, db: AsyncSession, note_id: str, user_id: str
    ) -> Note | None:
        statement = select(Note).where(Note.id == note_id, Note.user_id == user_id)
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def get_category_stats(self, db: AsyncSession, user_id: str) -> dict:
        # 【新增】先按当前用户分组，再从同一份结果算总数和未分类数。
        result = await db.execute(
            select(Note.category, func.count(Note.id))
            .where(Note.user_id == user_id)
            .group_by(Note.category)
        )
        categories = []
        uncategorized = 0
        total = 0
        for category, count in result.all():
            total += count
            if not category:
                uncategorized += count
            else:
                categories.append({"category": category, "count": count})
        return {"total": total, "categories": categories, "uncategorized": uncategorized}

    async def search_notes(
        self, db: AsyncSession, user_id: str, query: str,
        page: int = 1, page_size: int = 20,
    ) -> tuple[list[Note], int]:
        return await semantic_note_search(db, user_id, query, page, page_size)

    async def list_notes(
        self,
        db: AsyncSession,
        user_id: str,
        page: int = 1,
        page_size: int = 20,
        category: str | None = None,
        tag: str | None = None,
        sort_by: str = "updated_at",
    ) -> tuple[list[Note], int]:
        # 【修改 C01】先建立用户范围，任何后续分支都不能丢掉它。
        conditions = [Note.user_id == user_id]
        if category is not None:
            conditions.append(Note.category == category)

        sort_columns = {
            "updated_at": Note.updated_at,
            "created_at": Note.created_at,
            "title": Note.title,
        }
        if sort_by not in sort_columns:
            raise BusinessException(code=4002, message="不支持的排序字段")
        column = sort_columns[sort_by]
        primary_order = column.asc() if sort_by == "title" else column.desc()
        statement = select(Note).where(*conditions).order_by(
            Note.is_pinned.desc(), primary_order, Note.id.desc(),
        )
        offset = (page - 1) * page_size

        if tag is not None:
            # 【新增】先在当前用户/分类候选中精确匹配标签，再计算总数和切页。
            result = await db.execute(statement)
            candidates = list(result.scalars().all())
            matched = [note for note in candidates if tag in (note.tags or [])]
            total_count = len(matched)
            return matched[offset:offset + page_size], total_count

        # 【新增】无标签筛选时，在数据库完成 COUNT、LIMIT 和 OFFSET。
        count_statement = select(func.count(Note.id)).where(*conditions)
        total_count = int((await db.execute(count_statement)).scalar_one())
        result = await db.execute(statement.offset(offset).limit(page_size))
        return list(result.scalars().all()), total_count

    async def update_note(
        self, db: AsyncSession, note_id: str, user_id: str, payload: NoteUpdate
    ) -> Note | None:
        note = await self.get_note(db, note_id, user_id)
        if note is None:
            return None
        # 【新增 C02】只更新请求中明确给出的字段，保留其他值。
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            raise BusinessException(code=4001, message="没有提交可修改字段")
        content_changed = "content" in payload.model_fields_set
        for name, value in changes.items():
            setattr(note, name, value)
        await enqueue_graph(db, user_id, "note", note.id)
        await db.commit()
        await db.refresh(note)
        if content_changed:
            asyncio.create_task(enrich_note(note.id, user_id))
        return note

    async def delete_note(
        self, db: AsyncSession, note_id: str, user_id: str
    ) -> bool:
        note = await self.get_note(db, note_id, user_id)
        if note is None:
            return False
        await db.delete(note)
        await enqueue_graph(db, user_id, "note", note_id)
        await db.commit()
        return True

    async def batch_delete_notes(
        self, db: AsyncSession, user_id: str, ids: list[str]
    ) -> int:
        result = await db.execute(
            select(Note).where(Note.user_id == user_id, Note.id.in_(ids))
        )
        notes = list(result.scalars().all())
        for note in notes:
            await db.delete(note)
            await enqueue_graph(db, user_id, "note", note.id)
        # 【新增】查找与删除在同一请求会话里，只提交一次。
        await db.commit()
        return len(notes)

    async def batch_pin_notes(
        self, db: AsyncSession, user_id: str, ids: list[str], is_pinned: bool
    ) -> int:
        result = await db.execute(
            select(Note).where(Note.user_id == user_id, Note.id.in_(ids))
        )
        notes = list(result.scalars().all())
        for note in notes:
            note.is_pinned = is_pinned
        await db.commit()
        return len(notes)

    async def batch_update_category(
        self, db: AsyncSession, user_id: str, ids: list[str], category: str
    ) -> int:
        result = await db.execute(
            select(Note).where(Note.user_id == user_id, Note.id.in_(ids))
        )
        notes = list(result.scalars().all())
        for note in notes:
            note.category = category or None
        await db.commit()
        return len(notes)

    async def delete_category(
        self, db: AsyncSession, user_id: str, category: str
    ) -> int:
        result = await db.execute(
            select(Note).where(Note.user_id == user_id, Note.category == category)
        )
        notes = list(result.scalars().all())
        for note in notes:
            await db.delete(note)
            await enqueue_graph(db, user_id, "note", note.id)
        await db.commit()
        return len(notes)

    @staticmethod
    def _to_markdown(note: Note) -> str:
        # 【新增】元数据使用 JSON 编码，标题中的特殊字符不会破坏 frontmatter。
        header = [
            "---",
            f"title: {json.dumps(note.title, ensure_ascii=False)}",
            f"category: {json.dumps(note.category or '', ensure_ascii=False)}",
            f"tags: {json.dumps(note.tags or [], ensure_ascii=False)}",
            f"created_at: {json.dumps(note.created_at.isoformat())}",
            "---",
        ]
        return "\n".join(header) + "\n\n# " + note.title.replace("\n", " ") + "\n\n" + note.content + "\n"

    async def export_note_markdown(
        self, db: AsyncSession, user_id: str, note_id: str
    ) -> str | None:
        note = await self.get_note(db, note_id, user_id)
        return self._to_markdown(note) if note is not None else None

    async def batch_export_zip(
        self, db: AsyncSession, user_id: str, ids: list[str]
    ) -> bytes:
        result = await db.execute(
            select(Note).where(Note.user_id == user_id, Note.id.in_(ids))
        )
        by_id = {note.id: note for note in result.scalars().all()}
        buffer = BytesIO()
        with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as archive:
            for note_id in ids:
                note = by_id.get(note_id)
                if note is not None:
                    archive.writestr(f"{note.id}.md", self._to_markdown(note))
        return buffer.getvalue()

    async def toggle_pin(
        self, db: AsyncSession, note_id: str, user_id: str
    ) -> Note | None:
        note = await self.get_note(db, note_id, user_id)
        if note is None:
            return None
        note.is_pinned = not note.is_pinned
        await db.commit()
        await db.refresh(note)
        return note


note_service = NoteService()
