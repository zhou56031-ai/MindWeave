from sqlalchemy import JSON, Boolean, Column, DateTime, String, Text, func

from app.models.base import Base


class Note(Base):
    __tablename__ = "notes"

    # 【新增】字段与参考 Note 的核心结构对齐。
    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), index=True, nullable=False)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    tags = Column(JSON, nullable=True)
    category = Column(String(50), nullable=True)
    is_pinned = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )
