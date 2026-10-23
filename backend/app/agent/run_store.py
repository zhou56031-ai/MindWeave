"""MySQL 中的待审批运行：只按 JWT 用户身份访问。"""

from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from app.db.db_config import AsyncSessionLocal
from app.models.agent_run import AgentRun
from app.models.chat_history import ChatSession
from app.services.chat_session_service import chat_session_service


def approval_payload(proposal: dict) -> dict:
    return {
        "action_requests": [{
            "name": proposal["tool"],
            "args": proposal["arguments"],
            "description": proposal["description"],
        }],
        "review_configs": [{
            "action_name": proposal["tool"],
            "allowed_decisions": ["approve", "reject"],
        }],
    }


async def save_pending(
    user_id: str, session_id: str, existing_id: str | None,
    query: str, proposal: dict,
) -> AgentRun:
    async with AsyncSessionLocal() as db:
        session = await chat_session_service.ensure(
            db, user_id, existing_id, query[:60], new_id=session_id,
        )
        session = await db.scalar(select(ChatSession).where(
            ChatSession.id == session.id,
            ChatSession.user_id == user_id,
        ).with_for_update())
        if session is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        if session.pending_run_id:
            raise HTTPException(status_code=409, detail="此会话已有待审批操作")
        run = AgentRun(
            id=str(uuid4()), session_id=session.id, user_id=user_id,
            status="pending", query=query, proposal=proposal,
        )
        db.add(run)
        session.pending_run_id = run.id
        await db.commit()
        return run


async def pending(user_id: str, session_id: str) -> dict | None:
    async with AsyncSessionLocal() as db:
        session = await chat_session_service.owned(db, user_id, session_id)
        if not session.pending_run_id:
            return None
        run = await db.scalar(select(AgentRun).where(
            AgentRun.id == session.pending_run_id,
            AgentRun.user_id == user_id,
            AgentRun.session_id == session_id,
            AgentRun.status == "pending",
        ))
        if run is None:
            return None
        return {
            "run_id": run.id,
            "query": run.query,
            "payload": approval_payload(run.proposal),
        }


async def approval_snapshot(user_id: str, session_id: str) -> dict | None:
    async with AsyncSessionLocal() as db:
        session = await chat_session_service.owned(db, user_id, session_id)
        run = await db.scalar(
            select(AgentRun).where(
                AgentRun.session_id == session.id,
                AgentRun.user_id == user_id,
            ).order_by(AgentRun.updated_at.desc()).limit(1)
        )
        if run is None:
            return None
        return {
            "run_id": run.id,
            "query": run.query,
            "status": run.status,
            "active": (
                run.id == session.pending_run_id
                and run.status == "pending"
            ),
            "payload": approval_payload(run.proposal),
            "result": run.result,
        }


async def claim(user_id: str, session_id: str) -> tuple[str, dict, str, str]:
    async with AsyncSessionLocal() as db:
        session = await db.scalar(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.user_id == user_id,
            ).with_for_update()
        )
        if session is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        if not session.pending_run_id:
            raise HTTPException(status_code=409, detail="没有可恢复的审批")
        run = await db.scalar(select(AgentRun).where(
            AgentRun.id == session.pending_run_id,
            AgentRun.user_id == user_id,
            AgentRun.session_id == session_id,
        ).with_for_update())
        if run is None or run.status != "pending":
            raise HTTPException(status_code=409, detail="审批已处理或正在处理")
        run.status = "executing"
        await db.commit()
        return run.id, run.proposal, run.query, session_id


async def finish(
    user_id: str,
    session_id: str,
    run_id: str,
    status: str,
    result: str,
) -> None:
    if status not in {"completed", "rejected", "failed"}:
        raise ValueError("运行状态不支持")
    async with AsyncSessionLocal() as db:
        session = await db.scalar(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.user_id == user_id,
            ).with_for_update()
        )
        run = await db.scalar(select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.user_id == user_id,
            AgentRun.session_id == session_id,
        ).with_for_update())
        if session is None or run is None or run.status != "executing":
            raise HTTPException(status_code=409, detail="运行状态冲突")
        run.status = status
        run.result = result
        if session.pending_run_id == run_id:
            session.pending_run_id = None
        await db.commit()
