"""每个用户来源的最新一次抽取审计。"""

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint, func

from app.models.base import Base


class GraphExtractLog(Base):
    __tablename__ = "graph_extract_logs"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "source_kind", "source_id",
            name="uq_graph_extract_user_source",
        ),
    )

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), index=True, nullable=False)
    source_kind = Column(String(10), nullable=False)
    source_id = Column(String(36), nullable=False)
    content_hash = Column(String(32), nullable=False)
    status = Column(String(20), default="pending", nullable=False)
    new_count = Column(Integer, default=0, nullable=False)
    update_count = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)
    finished_at = Column(DateTime(), nullable=True)
    updated_at = Column(
        DateTime(), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
