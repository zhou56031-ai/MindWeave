"""长期记忆的读取、手动写入与偏好总结。"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_memory import UserMemory
from app.models.user_memory_summary import UserMemorySummary
from app.services.deepseek_client import deepseek_client

SUMMARY_PROMPT = """你是用户偏好整理助手。只根据给出的记忆条目，用中文总结 3-5 条稳定的偏好或习惯。
每条一行，以“- ”开头；不要编造记忆里没有的内容；信息不足时只输出已有的条目。"""


async def list_memories(db: AsyncSession, user_id: str) -> list[UserMemory]:
    rows = await db.scalars(
        select(UserMemory).where(UserMemory.user_id == user_id)
        .order_by(UserMemory.created_at.desc())
    )
    return list(rows.all())


async def add_memory(db: AsyncSession, user_id: str, content: str) -> UserMemory:
    memory = UserMemory(id=str(uuid4()), user_id=user_id, content=content.strip())
    db.add(memory)
    await db.commit()
    await db.refresh(memory)
    return memory


async def remove_memory(db: AsyncSession, user_id: str, memory_id: str) -> bool:
    result = await db.execute(delete(UserMemory).where(
        UserMemory.id == memory_id, UserMemory.user_id == user_id,
    ))
    await db.commit()
    return result.rowcount > 0


async def _generate(memories: list[UserMemory]) -> str:
    if not memories:
        return ""
    lines = "\n".join(f"- {item.content}" for item in memories)
    try:
        text = await deepseek_client.chat([
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": lines},
        ], max_tokens=400)
        return text.strip()
    except Exception:
        return lines


async def summary(db: AsyncSession, user_id: str) -> tuple[str, list[UserMemory]]:
    memories = await list_memories(db, user_id)
    cached = await db.get(UserMemorySummary, user_id)
    latest = memories[0].created_at if memories else None
    fresh = (
        cached is not None
        and cached.memory_count == len(memories)
        and (latest is None or cached.updated_at >= latest)
    )
    if fresh:
        return cached.summary, memories

    text = await _generate(memories)
    if cached is None:
        db.add(UserMemorySummary(user_id=user_id, summary=text, memory_count=len(memories)))
    else:
        cached.summary = text
        cached.memory_count = len(memories)
        cached.updated_at = datetime.now()
    await db.commit()
    return text, memories


memory_service = type("MemoryService", (), {
    "list": staticmethod(list_memories),
    "add": staticmethod(add_memory),
    "remove": staticmethod(remove_memory),
    "summary": staticmethod(summary),
})()
