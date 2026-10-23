"""可按用户和会话读取的上下文归档。"""
from sqlalchemy import Column, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.mysql import LONGTEXT
from app.models.base import Base


class ChatArtifact(Base):
    __tablename__ = "chat_artifacts"
    id = Column(String(36), primary_key=True)
    session_id = Column(String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id = Column(String(36), index=True, nullable=False)
    kind = Column(String(20), nullable=False)
    content = Column(LONGTEXT, nullable=False)
    created_at = Column(DateTime(), server_default=func.now(), nullable=False)
