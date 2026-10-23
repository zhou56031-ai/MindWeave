"""每个用户来源最多一条最新图构建任务。"""
from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.mysql import LONGTEXT
from app.models.base import Base


class GraphTask(Base):
    __tablename__ = "graph_tasks"
    __table_args__ = (
        UniqueConstraint("user_id", "source_kind", "source_id", name="uq_graph_task_source"),
    )

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), nullable=False, index=True)
    source_kind = Column(String(10), nullable=False)
    source_id = Column(String(36), nullable=False)
    title = Column(String(255), nullable=True)
    content_hash = Column(String(32), nullable=False, default="")
    payload = Column(Text().with_variant(LONGTEXT(), "mysql"), nullable=True)
    force = Column(Integer, default=0, nullable=False)
    # 【新增】片数是处理进度，版本成功切换后才登记。
    index_total = Column(Integer, default=0, nullable=False)
    index_done = Column(Integer, default=0, nullable=False)
    index_version = Column(String(40), default="", nullable=False)
    status = Column(String(20), default="pending", nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    run_token = Column(String(36), nullable=True)
    error_message = Column(Text, nullable=True)
    updated_at = Column(DateTime(), server_default=func.now(), onupdate=func.now(), nullable=False)
