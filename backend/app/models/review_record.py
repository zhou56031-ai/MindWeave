"""每篇笔记的回顾进度；当前阶段由笔记创建事务建立。这个是用来记录用户对于笔记的复习状态的"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from app.models.base import Base

class ReviewRecord(Base):
    __tablename__ = "review_records"
    __table_args__ = (UniqueConstraint("user_id", "note_id", name="uq_review_user_note"),)

    id = Column(String(36), primary_key=True)
    note_id = Column(String(36), ForeignKey("notes.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id = Column(String(36), index=True, nullable=False)
    last_reviewed_at = Column(DateTime(), nullable=True)
    review_count = Column(Integer, default=0, nullable=False)
    next_review_at = Column(DateTime(), nullable=False)
    interval_days = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime(), server_default=func.now(), nullable=False)
