"""Agent 请求的诊断记录，不承担业务断点恢复。"""
from sqlalchemy import Column, DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.mysql import LONGTEXT
from app.models.base import Base


class AgentTrace(Base):
    __tablename__ = "agent_traces"
    __table_args__ = (
        Index("ix_trace_user_session_time", "user_id", "session_id", "created_at"),
    )
    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), nullable=False)
    session_id = Column(String(36), nullable=False)
    status = Column(String(24), nullable=False)
    duration_ms = Column(Integer, nullable=False)
    payload = Column(Text().with_variant(LONGTEXT(), "mysql"), nullable=False)
    created_at = Column(DateTime(), server_default=func.now(), index=True, nullable=False)
