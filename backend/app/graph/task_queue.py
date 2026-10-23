"""与原业务写入共用 MySQL 事务的任务登记。"""
import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.graph_task import GraphTask


async def enqueue_graph(
    db: AsyncSession,
    user_id: str,
    source_kind: str,
    source_id: str,
    *,
    title: str = "",
    content_hash: str | None = None,
    payload: dict | None = None,
    force: bool = False,
) -> None:
    if source_kind not in {"note", "doc"}:
        raise ValueError("来源类型不支持")
    row = await db.scalar(
        select(GraphTask).where(
            GraphTask.user_id == user_id,
            GraphTask.source_kind == source_kind,
            GraphTask.source_id == source_id,
        ).with_for_update()
    )
    if row is None:
        db.add(GraphTask(
            id=str(uuid4()), user_id=user_id, source_kind=source_kind,
            source_id=source_id, title=title,
            content_hash=content_hash or "",
            payload=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
            force=int(force), status="pending", attempts=0,
        ))
    else:
        if title:
            row.title = title
        if content_hash is not None:
            row.content_hash = content_hash
        if payload is not None:
            row.payload = json.dumps(payload, ensure_ascii=False)
        row.force = int(force)
        row.status = "pending"
        row.attempts = 0
        row.run_token = None
        row.error_message = None
        row.index_done = 0
        row.index_total = 0
    # 调用方与原业务行一起 commit；这里绝不提前提交。
