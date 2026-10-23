"""聊天会话和消息表，复用应用统一 Base。"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, func

from app.models.base import Base


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), index=True, nullable=False)
    title = Column(String(255), default="新的对话", nullable=False)
    pending_run_id = Column(String(64), nullable=True)
    metadata_ = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(), server_default=func.now(), onupdate=func.now(), nullable=False)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True, nullable=False)
    role = Column(String(32), nullable=False)
    content = Column(Text, nullable=False)
    metadata_ = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime(), server_default=func.now(), nullable=False)
