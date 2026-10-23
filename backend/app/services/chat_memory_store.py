"""原始聊天、压缩状态与归档的数据库边界。"""
import copy
from datetime import UTC, datetime
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import func, select
from app.db.db_config import AsyncSessionLocal
from app.models.chat_artifact import ChatArtifact
from app.models.chat_history import ChatMessage, ChatSession
from app.services.chat_context import AgentContext
from app.services.chat_session_service import chat_session_service


class ChatMemoryStore:
    def __init__(self, user_id: str, session_id: str):
        self.user_id = user_id
        self.session_id = session_id

    async def start(self, existing_id: str | None, query: str) -> None:
        async with AsyncSessionLocal() as db:
            session = await chat_session_service.ensure(
                db, self.user_id, existing_id, query[:60], new_id=self.session_id,
            )
            if session.pending_run_id:
                raise HTTPException(409, "PENDING_EXISTS")
            # 新会话先存在，工具归档才能挂外键；失败时可能留下空会话。
            await db.commit()

    async def archive(self, kind: str, content: str) -> str:
        async with AsyncSessionLocal() as db:
            await chat_session_service.owned(db, self.user_id, self.session_id)
            artifact_id = str(uuid4())
            db.add(ChatArtifact(
                id=artifact_id, user_id=self.user_id, session_id=self.session_id,
                kind=kind, content=content,
            ))
            await db.commit()
            return artifact_id

    async def read_artifact(self, artifact_id: str, offset: int) -> dict:
        async with AsyncSessionLocal() as db:
            await chat_session_service.owned(db, self.user_id, self.session_id)
            # SQL 层分页，不把完整 LONGTEXT 每次读进 Python。
            row = (await db.execute(select(
                func.substr(ChatArtifact.content, offset + 1, 2000),
                func.char_length(ChatArtifact.content),
            ).where(
                ChatArtifact.id == artifact_id,
                ChatArtifact.user_id == self.user_id,
                ChatArtifact.session_id == self.session_id,
            ))).first()
            if row is None:
                raise HTTPException(404, "归档不存在")
            content, total = row
            return {"artifact_id": artifact_id, "offset": offset,
                    "content": content, "next_offset": offset + 2000 if offset + 2000 < total else None}

    async def load(self, system: str, tools: list[dict]) -> AgentContext:
        async with AsyncSessionLocal() as db:
            session = await chat_session_service.owned(db, self.user_id, self.session_id)
            saved = copy.deepcopy((session.metadata_ or {}).get("agent_context", {}))
            high = await db.scalar(select(func.max(ChatMessage.id)).where(
                ChatMessage.session_id == self.session_id,
            )) or 0
        cursor = int(saved.get("through_id", 0))
        context = AgentContext(
            messages=saved.get("messages", []), summary=saved.get("summary", {}),
            archives=saved.get("archives", []),
        )
        while cursor < high:
            async with AsyncSessionLocal() as db:
                await chat_session_service.owned(db, self.user_id, self.session_id)
                rows = (await db.execute(select(ChatMessage).where(
                    ChatMessage.session_id == self.session_id,
                    ChatMessage.id > cursor, ChatMessage.id <= high,
                ).order_by(ChatMessage.id).limit(20))).scalars().all()
            if not rows:
                break
            for row in rows:
                if row.role in {"user", "assistant"}:
                    context.messages.append({"role": row.role, "content": row.content})
                    await context.prepare(system, tools, self.archive)
                cursor = row.id
        await context.prepare(system, tools, self.archive)
        return context

    async def finish(self, query: str, answer: str, context: AgentContext) -> None:
        async with AsyncSessionLocal() as db:
            session = await db.scalar(select(ChatSession).where(
                ChatSession.id == self.session_id, ChatSession.user_id == self.user_id,
            ).with_for_update())
            if session is None or session.pending_run_id:
                raise HTTPException(409, "会话已删除或存在待审批操作")
            db.add(ChatMessage(session_id=self.session_id, role="user", content=query, metadata_={}))
            final = ChatMessage(session_id=self.session_id, role="assistant", content=answer, metadata_={})
            db.add(final)
            await db.flush()
            saved = {**context.dump(), "through_id": final.id}
            session.metadata_ = {**(session.metadata_ or {}), "agent_context": saved}
            session.updated_at = datetime.now(UTC).replace(tzinfo=None)
            await db.commit()
