"""诊断落库与用户范围读取；落库失败不替换已完成的业务结果。"""
import asyncio
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from fastapi import HTTPException
from sqlalchemy import delete, select
from app.core.agent_trace import TraceBuffer
from app.core.settings import settings
from app.db.db_config import AsyncSessionLocal
from app.models.agent_trace import AgentTrace

logger = logging.getLogger("mindweave.agent_trace")
_pending = set()


async def _save(trace: TraceBuffer) -> None:
    try:
        async with asyncio.timeout(2):
            async with AsyncSessionLocal() as db:
                cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=settings.AGENT_TRACE_KEEP_DAYS)
                await db.execute(delete(AgentTrace).where(AgentTrace.created_at < cutoff))
                db.add(AgentTrace(
                    id=trace.id, user_id=trace.user_id, session_id=trace.session_id,
                    status=trace.status,
                    duration_ms=round((time.perf_counter() - trace.started) * 1000),
                    payload=json.dumps(trace.payload(), ensure_ascii=False),
                ))
                await db.commit()
    except Exception as exc:
        logger.warning("agent_trace_save_failed run_id=%s error_type=%s", trace.id, type(exc).__name__)


async def save_trace(trace: TraceBuffer) -> None:
    task = asyncio.create_task(_save(trace), name="save-agent-trace")
    _pending.add(task)
    task.add_done_callback(_pending.discard)
    # 外部取消不立即打断落库；进程崩溃仍可能丢失，不能当持久消息队列。
    await asyncio.shield(task)


async def list_traces(db, user_id: str, session_id: str) -> list[dict]:
    rows = (await db.execute(select(AgentTrace).where(
        AgentTrace.user_id == user_id, AgentTrace.session_id == session_id,
    ).order_by(AgentTrace.created_at.desc(), AgentTrace.id.desc()).limit(30))).scalars().all()
    return [{"run_id": row.id, "status": row.status, "duration_ms": row.duration_ms,
             "created_at": row.created_at} for row in rows]


async def get_trace(db, user_id: str, run_id: str) -> dict:
    row = await db.scalar(select(AgentTrace).where(
        AgentTrace.id == run_id, AgentTrace.user_id == user_id,
    ))
    if row is None:
        raise HTTPException(404, "诊断记录不存在")
    return {"run_id": row.id, "session_id": row.session_id, "status": row.status,
            "duration_ms": row.duration_ms, "created_at": row.created_at,
            **json.loads(row.payload)}
