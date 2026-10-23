"""把超时 running 工单重新放回可处理队列。"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.db_config import AsyncSessionLocal
from app.models.graph_task import GraphTask

STALE_AFTER = timedelta(minutes=30)


async def recover_stale() -> int:
    cutoff = datetime.now(UTC).replace(tzinfo=None) - STALE_AFTER
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(GraphTask).where(
                GraphTask.status == "running",
                GraphTask.updated_at < cutoff,
            ).with_for_update(skip_locked=True)
        )).scalars().all()
        for row in rows:
            row.status = "pending" if row.attempts < 3 else "failed"
            row.run_token = None
            row.error_message = (
                "Worker 超时，已回收"
                if row.status == "pending"
                else "重试次数耗尽"
            )
        await db.commit()
        return len(rows)
