"""按进程复用 MySQL checkpointer。"""

from app.agent.checkpoint.mysql_saver import MySQLCheckpointSaver
from app.db.db_config import AsyncSessionLocal

_saver: MySQLCheckpointSaver | None = None


def get_checkpointer() -> MySQLCheckpointSaver:
    global _saver
    if _saver is None:
        _saver = MySQLCheckpointSaver(session_factory=AsyncSessionLocal)
    return _saver


def checkpoint_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}
