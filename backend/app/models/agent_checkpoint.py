"""LangGraph 状态快照与中间写入。"""

from sqlalchemy import Column, Integer, LargeBinary, String
from sqlalchemy.dialects.mysql import LONGBLOB

from app.models.base import Base


class AgentCheckpoint(Base):
    __tablename__ = "agent_checkpoints"

    thread_id = Column(String(255), primary_key=True, index=True)
    checkpoint_ns = Column(String(255), primary_key=True, default="")
    checkpoint_id = Column(String(64), primary_key=True)
    parent_checkpoint_id = Column(String(64), nullable=True)
    type = Column(String(64), nullable=True)
    checkpoint = Column(LargeBinary().with_variant(LONGBLOB(), "mysql"))
    metadata_ = Column(
        LargeBinary().with_variant(LONGBLOB(), "mysql"), name="metadata",
    )


class AgentCheckpointWrite(Base):
    __tablename__ = "agent_checkpoint_writes"

    thread_id = Column(String(255), primary_key=True)
    checkpoint_ns = Column(String(255), primary_key=True, default="")
    checkpoint_id = Column(String(64), primary_key=True)
    task_id = Column(String(64), primary_key=True)
    idx = Column(Integer, primary_key=True)
    channel = Column(String(255), nullable=False)
    type = Column(String(64), nullable=True)
    value = Column(LargeBinary().with_variant(LONGBLOB(), "mysql"))
