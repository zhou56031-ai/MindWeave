"""聊天会话与流式问答 HTTP 接口。"""

from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.approval_stream import resume_events
from app.agent.run_store import approval_snapshot, pending
from app.core.rate_limit import rate_limit
from app.core.success_response import success_response
from app.core.settings import settings
from app.db.db_config import get_db
from app.rag.reorder import reorder
from app.schemas.models import ChatQueryRequest
from app.services.chat_session_service import chat_session_service
from app.services.chat_stream_service import chat_events
from app.services.usage_service import usage_service
from app.utils.auth_utils import get_current_user_id
from app.services.agent_trace_store import get_trace, list_traces

chat_router = APIRouter(prefix="/chat", tags=["chat"])
chat_rate_limit = rate_limit("chat", settings.RATE_LIMIT_CHAT_PER_MINUTE)


class ApprovalDecision(BaseModel):
    type: Literal["approve", "reject"]
    message: str | None = Field(default=None, max_length=500)


class ResumeRequest(BaseModel):
    session_id: str
    decisions: list[ApprovalDecision] = Field(min_length=1, max_length=1)


class ReorderRequest(BaseModel):
    query: str = Field(min_length=1, max_length=100)
    documents: list[str] = Field(max_length=20)


@chat_router.post("/agent/query/stream")
async def query_stream(
    payload: ChatQueryRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(chat_rate_limit),
) -> StreamingResponse:
    if payload.session_id is not None:
        await chat_session_service.owned(db, user_id, payload.session_id)
        await db.rollback()
    chosen_id = payload.session_id or str(uuid4())
    trace_run_id = str(uuid4())
    return StreamingResponse(
        chat_events(user_id, payload.query, chosen_id, payload.session_id, run_id=trace_run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Agent-Run-ID": trace_run_id},
    )


@chat_router.get("/session/{session_id}/pending")
async def get_pending(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
) -> JSONResponse:
    return success_response(data=await pending(user_id, session_id))


@chat_router.get("/session/{session_id}/approval")
async def get_approval(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
) -> JSONResponse:
    return success_response(data=await approval_snapshot(user_id, session_id))


@chat_router.post("/agent/resume")
async def resume(
    payload: ResumeRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(chat_rate_limit),
) -> StreamingResponse:
    await chat_session_service.owned(db, user_id, payload.session_id)
    await db.rollback()
    return StreamingResponse(
        resume_events(user_id, payload.session_id, payload.decisions[0].type),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@chat_router.post("/reorder")
async def reorder_documents(
    payload: ReorderRequest,
    user_id: str = Depends(get_current_user_id),
    _: None = Depends(chat_rate_limit),
) -> JSONResponse:
    if any(not item or len(item) > 2000 for item in payload.documents):
        raise HTTPException(status_code=422, detail="候选文档过长或为空")
    return success_response(data={
        "documents": await reorder(payload.query, payload.documents),
    })


@chat_router.get("/sessions")
async def list_sessions(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return success_response(data={"sessions": await chat_session_service.list_for_user(db, user_id)})


@chat_router.get("/sessions/{path_user_id}")
async def list_user_sessions(
    path_user_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if path_user_id != user_id:
        raise HTTPException(status_code=403, detail="无权查看该用户会话")
    return success_response(data={"sessions": await chat_session_service.list_for_user(db, user_id)})


@chat_router.get("/session/{session_id}")
async def get_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return success_response(data=await chat_session_service.detail(db, user_id, session_id))


@chat_router.get("/usage")
async def usage_summary(
    days: int = 30,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return success_response(data=await usage_service.summary(db, user_id, max(1, min(days, 365))))


@chat_router.get("/usage/{session_id}")
async def usage_detail(
    session_id: str,
    days: int = 30,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return success_response(data=await usage_service.detail(
        db, user_id, session_id, max(1, min(days, 365)),
    ))


@chat_router.delete("/session/{session_id}")
async def delete_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await chat_session_service.delete(db, user_id, session_id)
    return success_response(message="会话已删除")


@chat_router.get("/session/{session_id}/traces")
async def session_traces(
    session_id: str, user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await chat_session_service.owned(db, user_id, session_id)
    return success_response(data=await list_traces(db, user_id, session_id))


@chat_router.get("/traces/{trace_run_id}")
async def trace_detail(
    trace_run_id: str, user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return success_response(data=await get_trace(db, user_id, trace_run_id))
