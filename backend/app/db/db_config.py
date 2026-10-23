from collections.abc import AsyncIterator

from sqlalchemy import URL, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.settings import settings
from app.models.base import Base

# 【新增】用结构化 URL 处理密码中的 @、: 等字符。
database_url = URL.create(
    drivername="mysql+aiomysql",
    username=settings.MYSQL_USER,
    password=settings.MYSQL_PASSWORD.get_secret_value(),
    host=settings.MYSQL_HOST,
    port=settings.MYSQL_PORT,
    database=settings.MYSQL_DATABASE,
    query={"charset": "utf8mb4"},
)

async_engine = create_async_engine(
    database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    # 【新增】每个请求拿独立会话；写入提交由服务层明确执行。
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def check_mysql_connection() -> bool:
    try:
        async with async_engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def init_db() -> None:
    # 【新增 C01】导入模型完成注册后，统一检查并创建缺失表。
    from app.models.note import Note  # noqa: F401
    from app.models.user_model import User  # noqa: F401
    from app.models.note_template import NoteTemplate  # noqa: F401
    from app.models.knowledge_document import KnowledgeDocument, KnowledgeChunk  # noqa: F401
    from app.models.review_record import ReviewRecord  # noqa: F401
    from app.models.chat_history import ChatSession, ChatMessage  # noqa: F401
    from app.models.chat_artifact import ChatArtifact  # noqa: F401
    from app.models.agent_trace import AgentTrace  # noqa: F401
    from app.models.agent_run import AgentRun  # noqa: F401
    from app.models.agent_checkpoint import (  # noqa: F401
        AgentCheckpoint,
        AgentCheckpointWrite,
    )
    from app.models.graph_task import GraphTask  # noqa: F401
    from app.models.graph_extract_log import GraphExtractLog  # noqa: F401
    from app.models.user_memory import UserMemory  # noqa: F401
    from app.models.user_memory_summary import UserMemorySummary  # noqa: F401

    async with async_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await _ensure_graph_task_columns(connection)
        await _ensure_chunk_parent_columns(connection)


async def _ensure_graph_task_columns(connection) -> None:
    """让既有 MySQL 表获得 create_all 不会自动添加的列。"""

    def column_names(sync_connection) -> set[str]:
        inspector = inspect(sync_connection)
        if not inspector.has_table("graph_tasks"):
            return set()
        return {column["name"] for column in inspector.get_columns("graph_tasks")}

    existing = await connection.run_sync(column_names)
    changes = {
        "title": "ADD COLUMN `title` VARCHAR(255) NULL",
        "content_hash": (
            "ADD COLUMN `content_hash` VARCHAR(32) NOT NULL DEFAULT ''"
        ),
        "payload": "ADD COLUMN `payload` LONGTEXT NULL",
        "force": "ADD COLUMN `force` INT NOT NULL DEFAULT 0",
        "index_total": "ADD COLUMN `index_total` INT NOT NULL DEFAULT 0",
        "index_done": "ADD COLUMN `index_done` INT NOT NULL DEFAULT 0",
        "index_version": "ADD COLUMN `index_version` VARCHAR(40) NOT NULL DEFAULT ''",
    }
    for name, operation in changes.items():
        if name not in existing:
            await connection.execute(text(
                f"ALTER TABLE `graph_tasks` {operation}"
            ))

async def _ensure_chunk_parent_columns(connection) -> None:
    """为既有 knowledge_chunks 表补父子块列（只加列，不改旧数据）。"""

    def column_names(sync_connection) -> set[str]:
        inspector = inspect(sync_connection)
        if not inspector.has_table("knowledge_chunks"):
            return set()
        return {column["name"] for column in inspector.get_columns("knowledge_chunks")}

    existing = await connection.run_sync(column_names)
    changes = {
        "parent_id": "ADD COLUMN `parent_id` VARCHAR(64) NULL",
        "parent_text": "ADD COLUMN `parent_text` TEXT NULL",
    }
    for name, operation in changes.items():
        if name not in existing:
            await connection.execute(text(
                f"ALTER TABLE `knowledge_chunks` {operation}"
            ))
