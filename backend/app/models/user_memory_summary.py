"""用户偏好总结缓存：记忆条数变化时重新生成。"""
from sqlalchemy import Column, DateTime, Integer, String, Text, func

from app.models.base import Base


class UserMemorySummary(Base):
    __tablename__ = "user_memory_summaries"

    user_id = Column(String(36), primary_key=True)
    summary = Column(Text, nullable=False)
    memory_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(), server_default=func.now(), onupdate=func.now(), nullable=False)
