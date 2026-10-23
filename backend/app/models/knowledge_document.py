"""知识文档及其切片在 MySQL 中的结构。"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.mysql import LONGTEXT

from app.models.base import Base


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("user_id", "filename", name="uq_knowledge_user_filename"),
        UniqueConstraint("user_id", "md5", name="uq_knowledge_user_md5"),
    )

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), index=True, nullable=False)
    filename = Column(String(255), nullable=False)
    md5 = Column(String(32), nullable=False)
    file_size = Column(Integer, nullable=False)
    content = Column(LONGTEXT, nullable=False)
    status = Column(String(20), default="completed", nullable=False)
    chunk_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(), server_default=func.now(), nullable=False)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id = Column(String(36), primary_key=True)
    document_id = Column(
        String(36), ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    page = Column(Integer, nullable=True)
    images = Column(JSON, default=list, nullable=False)
    # 【新增】父子块：子块用于召回，父块用于回填上下文。
    parent_id = Column(String(64), index=True, nullable=True)
    parent_text = Column(Text, nullable=True)
