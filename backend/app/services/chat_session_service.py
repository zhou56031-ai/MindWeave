"""聊天会话的用户范围查询与持久化。"""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_history import ChatMessage, ChatSession
from app.models.agent_trace import AgentTrace
from app.schemas.models import ChatSessionDetail, ChatSessionResponse
from app.services.chat_context import bounded_history


class ChatSessionService:
    @staticmethod
    def _view(session: ChatSession) -> ChatSessionResponse:
        return ChatSessionResponse(
            id=session.id, user_id=session.user_id, title=session.title,
            metadata={k: v for k, v in (session.metadata_ or {}).items() if k != "agent_context"}, created_at=session.created_at,
            updated_at=session.updated_at, pending_run_id=session.pending_run_id,
        )

    async def list_for_user(self, db: AsyncSession, user_id: str) -> list[ChatSessionResponse]:
        rows = await db.execute(
            select(ChatSession).where(ChatSession.user_id == user_id)
            .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
        )
        return [self._view(row) for row in rows.scalars().all()]

    async def owned(self, db: AsyncSession, user_id: str, session_id: str) -> ChatSession:
        row = await db.scalar(select(ChatSession).where(
            ChatSession.id == session_id, ChatSession.user_id == user_id,
        ))
        if row is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        return row

    # 【新增】用于模型输入的历史与前端完整历史分别读取。
    async def history_for_model(
        self, db: AsyncSession, user_id: str, session_id: str | None,
    ) -> list[dict[str, str]]:
        if session_id is None:
            return []
        session = await self.owned(db, user_id, session_id)
        rows = await db.execute(
            select(ChatMessage).where(ChatMessage.session_id == session.id)
            .order_by(ChatMessage.id.desc()).limit(12)
        )
        messages = list(reversed(rows.scalars().all()))
        return bounded_history([
            {"role": row.role, "content": row.content} for row in messages
        ])

    async def detail(self, db: AsyncSession, user_id: str, session_id: str) -> ChatSessionDetail:
        session = await self.owned(db, user_id, session_id)
        rows = await db.execute(
            select(ChatMessage).where(ChatMessage.session_id == session.id)
            .order_by(ChatMessage.id.asc())
        )
        return ChatSessionDetail(
            session_id=session.id,
            history=[(row.role, row.content) for row in rows.scalars().all()],
            pending_run_id=session.pending_run_id,
        )

    async def delete(self, db: AsyncSession, user_id: str, session_id: str) -> None:
        session = await self.owned(db, user_id, session_id)
        await db.execute(delete(AgentTrace).where(
            AgentTrace.user_id == user_id, AgentTrace.session_id == session_id,
        ))
        await db.delete(session)
        await db.commit()
        try:
            from app.agent.checkpoint.factory import get_checkpointer
            await get_checkpointer().adelete_thread(session.id)
        except Exception:
            pass

    async def ensure(
        self, db: AsyncSession, user_id: str, session_id: str | None,
        title: str, *, new_id: str | None = None,
    ) -> ChatSession:
        if session_id is not None:
            return await self.owned(db, user_id, session_id)
        session = ChatSession(
            id=new_id or str(uuid4()), user_id=user_id,
            title=title[:255], metadata_={},
        )
        db.add(session)
        await db.flush()
        return session

    async def append_turn(
        self, db: AsyncSession, session: ChatSession, query: str, answer: str
    ) -> None:
        db.add(ChatMessage(session_id=session.id, role="user", content=query, metadata_={}))
        db.add(ChatMessage(session_id=session.id, role="assistant", content=answer, metadata_={}))
        # 消息新增不会自动触发父会话的 onupdate；主动记录最后活动时间。
        session.updated_at = datetime.now(UTC).replace(tzinfo=None)
        await db.commit()


chat_session_service = ChatSessionService()
