"""一次工具审批运行的持久记录。"""

from sqlalchemy import Column, DateTime, ForeignKey, JSON, String, Text, func

from app.models.base import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(String(36), primary_key=True)
    session_id = Column(
        String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    user_id = Column(String(36), index=True, nullable=False)
    status = Column(String(20), default="pending", nullable=False)
    query = Column(Text, nullable=False)
    proposal = Column(JSON, nullable=False)
    result = Column(Text, nullable=True)
    created_at = Column(DateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
