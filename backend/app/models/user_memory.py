"""跨会话长期记忆（只存用户显式确认的内容）。"""
from sqlalchemy import Column, DateTime, String, Text, func

from app.models.base import Base


class UserMemory(Base):
    __tablename__ = "user_memories"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), index=True, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(), server_default=func.now(), nullable=False)
