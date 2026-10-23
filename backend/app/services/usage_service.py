"""按会话聚合 agent_traces 的 token 与耗时。"""
import json
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_trace import AgentTrace
from app.models.chat_history import ChatSession


def _usage_from_payload(payload: str) -> dict:
    try:
        data = json.loads(payload or "{}")
    except json.JSONDecodeError:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                "model_calls": 0, "tool_calls": 0}
    input_tokens = output_tokens = total_tokens = model_calls = tool_calls = 0
    for event in data.get("events", []):
        name = event.get("name")
        info = event.get("data") or {}
        if name == "request.usage" and not info.get("error_type"):
            input_tokens += int(info.get("input_tokens") or 0)
            output_tokens += int(info.get("output_tokens") or 0)
            total_tokens += int(info.get("total_tokens") or 0)
            model_calls += 1
        elif name == "agent.tool.end":
            tool_calls += 1
    return {"input_tokens": input_tokens, "output_tokens": output_tokens,
            "total_tokens": total_tokens, "model_calls": model_calls,
            "tool_calls": tool_calls}


async def summary(db: AsyncSession, user_id: str, days: int) -> dict:
    since = datetime.now() - timedelta(days=days)
    sessions = (await db.scalars(
        select(ChatSession).where(ChatSession.user_id == user_id)
        .order_by(ChatSession.updated_at.desc())
    )).all()
    traces = (await db.scalars(
        select(AgentTrace).where(
            AgentTrace.user_id == user_id, AgentTrace.created_at >= since,
        )
    )).all()

    grouped: dict[str, list[AgentTrace]] = {}
    for trace in traces:
        grouped.setdefault(trace.session_id, []).append(trace)

    items = []
    for session in sessions:
        rows = grouped.get(session.id, [])
        usage = [_usage_from_payload(row.payload) for row in rows]
        totals = {
            key: sum(item[key] for item in usage)
            for key in ("input_tokens", "output_tokens", "total_tokens", "model_calls", "tool_calls")
        }
        duration = sum(row.duration_ms for row in rows)
        last_at = max((row.created_at for row in rows), default=session.updated_at)
        items.append({
            "session_id": session.id,
            "title": session.title,
            "requests": len(rows),
            "input_tokens": totals["input_tokens"],
            "output_tokens": totals["output_tokens"],
            "total_tokens": totals["total_tokens"],
            "model_calls": totals["model_calls"],
            "tool_calls": totals["tool_calls"],
            "duration_ms": duration,
            "avg_duration_ms": round(duration / len(rows)) if rows else 0,
            "last_at": last_at.isoformat() if last_at else None,
            "created_at": session.created_at.isoformat() if session.created_at else None,
        })
    items.sort(key=lambda item: item["last_at"] or "", reverse=True)
    return {"days": days, "sessions": items}


async def detail(db: AsyncSession, user_id: str, session_id: str, days: int) -> dict:
    session = await db.scalar(select(ChatSession).where(
        ChatSession.id == session_id, ChatSession.user_id == user_id,
    ))
    if session is None:
        return {"session_id": session_id, "title": "", "requests": []}
    since = datetime.now() - timedelta(days=days)
    traces = (await db.scalars(
        select(AgentTrace).where(
            AgentTrace.user_id == user_id,
            AgentTrace.session_id == session_id,
            AgentTrace.created_at >= since,
        ).order_by(AgentTrace.created_at.desc())
    )).all()
    requests = []
    for trace in traces:
        usage = _usage_from_payload(trace.payload)
        requests.append({
            "trace_id": trace.id,
            "created_at": trace.created_at.isoformat() if trace.created_at else None,
            "status": trace.status,
            "duration_ms": trace.duration_ms,
            **usage,
        })
    return {"session_id": session_id, "title": session.title, "requests": requests}


usage_service = type("UsageService", (), {"summary": staticmethod(summary), "detail": staticmethod(detail)})()
