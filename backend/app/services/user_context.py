"""把长期记忆与技能目录拼进 system prompt。"""
from sqlalchemy import select

from app.db.db_config import AsyncSessionLocal
from app.models.user_memory import UserMemory
from app.services import skill_service


async def augment_system(base: str, user_id: str) -> str:
    names = skill_service.catalog()
    skills = ("\n可用技能（需要细节时调用 load_skill）：\n" +
              "\n".join(f"- {name}" for name in names)) if names else ""
    memories = []
    try:
        if not user_id:
            raise ValueError("missing user")
        async with AsyncSessionLocal() as db:
            memories = (await db.scalars(
                select(UserMemory).where(UserMemory.user_id == user_id)
                .order_by(UserMemory.created_at.desc()).limit(20)
            )).all()
    except Exception:
        memories = []
    memory_text = ("\n[用户长期记忆]\n" + "\n".join(f"- {item.content}" for item in memories)
                   if memories else "")
    return f"{base}{skills}{memory_text}"
