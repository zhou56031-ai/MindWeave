"""把工具名映射到当前用户的业务服务。"""

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from uuid import uuid4

from app.agent.tool_schemas import (
    CreateNoteArgs,
    MarkReviewedArgs,
    RelatedNotesArgs,
    RememberArgs,
    ToolChoice,
)
from app.models.user_memory import UserMemory
from app.rag.related import related_fragments
from app.services.note_service import note_service
from app.services.review_service import review_service


async def read_tool(
    db: AsyncSession, user_id: str, choice: ToolChoice,
) -> str | None:
    if choice.tool == "none":
        return None
    if choice.tool == "search_notes":
        query = str(choice.arguments.get("query", "")).strip()[:100]
        if not query:
            raise HTTPException(status_code=422, detail="搜索词为空")
        notes, _ = await note_service.search_notes(db, user_id, query, 1, 5)
        return "\n".join(
            f"{note.id} | {note.title} | {note.content[:200]}"
            for note in notes
        ) or "没有找到笔记"
    if choice.tool == "note_stats":
        return str(await note_service.get_category_stats(db, user_id))
    if choice.tool == "today_reviews":
        today = await review_service.today(db, user_id)
        return "\n".join(
            f"{item.note_id} | {item.title}" for item in today.reviews
        ) or "今日没有待回顾笔记"
    if choice.tool == "what_time":
        return datetime.now().strftime("当前本地时间：%Y-%m-%d %H:%M")
    if choice.tool == "get_user_info":
        return f"当前用户 ID：{user_id}"
    if choice.tool == "related_notes":
        args = RelatedNotesArgs.model_validate(choice.arguments)
        items = await related_fragments(db, user_id, args.note_id)
        return "\n".join(
            f"{item['id']} | {item['title']} | {item['similarity']}"
            for item in items
        ) or "没有找到相关笔记"
    return None


def write_proposal(choice: ToolChoice) -> dict | None:
    if choice.tool == "create_note":
        args = CreateNoteArgs.model_validate(choice.arguments)
        return {
            "tool": "create_note",
            "arguments": args.model_dump(),
            "description": f"创建笔记：{args.title}",
        }
    if choice.tool == "remember":
        args = RememberArgs.model_validate(choice.arguments)
        return {
            "tool": "remember", "arguments": args.model_dump(),
            "description": f"记住：{args.content[:60]}",
        }
    if choice.tool == "mark_reviewed":
        args = MarkReviewedArgs.model_validate(choice.arguments)
        return {
            "tool": "mark_reviewed",
            "arguments": args.model_dump(),
            "description": f"标记回顾：{args.note_id}",
        }
    return None


async def execute_approved_write(
    db: AsyncSession, user_id: str, proposal: dict,
) -> str:
    if proposal["tool"] == "create_note":
        args = CreateNoteArgs.model_validate(proposal["arguments"])
        from app.schemas.models import NoteCreate
        note = await note_service.create_note(
            db, user_id, NoteCreate(title=args.title, content=args.content),
        )
        return f"已创建笔记 {note.title}，ID {note.id}"
    if proposal["tool"] == "remember":
        args = RememberArgs.model_validate(proposal["arguments"])
        memory = UserMemory(id=str(uuid4()), user_id=user_id, content=args.content)
        db.add(memory)
        await db.commit()
        return f"已记住：{args.content[:60]}"
    if proposal["tool"] == "mark_reviewed":
        args = MarkReviewedArgs.model_validate(proposal["arguments"])
        result = await review_service.mark_done(db, user_id, args.note_id)
        return f"已完成第 {result.review_count} 次回顾"
    raise HTTPException(status_code=422, detail="未知写入工具")
