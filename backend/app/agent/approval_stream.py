"""审批恢复后的 SSE：写操作先落地，再解释结果。"""

import asyncio
from collections.abc import AsyncIterator

from fastapi import HTTPException

from app.agent.run_store import claim, finish
from app.agent.session_lease import session_lease
from app.agent.tools import execute_approved_write
from app.db.db_config import AsyncSessionLocal
from app.services.chat_session_service import chat_session_service
from app.services.chat_stream_service import frame
from app.services.deepseek_client import deepseek_client


async def resume_events(
    user_id: str, session_id: str, decision: str,
) -> AsyncIterator[str]:
    try:
        async with session_lease(user_id, session_id):
            async with asyncio.timeout(180):
                async for event in _resume_events(user_id, session_id, decision):
                    yield event
    except HTTPException as exc:
        yield frame({"type": "error", "content": str(exc.detail)})
        yield frame({"type": "done", "session_id": session_id})
    except Exception:
        yield frame({"type": "error", "content": "审批恢复中断，请先核对操作状态，不要重复执行"})
        yield frame({"type": "done", "session_id": session_id})


async def _resume_events(
    user_id: str, session_id: str, decision: str,
) -> AsyncIterator[str]:
    try:
        run_id, proposal, query, _ = await claim(user_id, session_id)
    except HTTPException as exc:
        yield frame({"type": "error", "content": str(exc.detail)})
        yield frame({"type": "done", "session_id": session_id})
        return

    if decision == "reject":
        answer = "已取消这项操作，没有写入数据。"
        await finish(user_id, session_id, run_id, "rejected", answer)
        async with AsyncSessionLocal() as db:
            session = await chat_session_service.owned(db, user_id, session_id)
            await chat_session_service.append_turn(db, session, query, answer)
        yield frame({
            "type": "response", "content": answer, "session_id": session_id,
        })
        yield frame({"type": "done", "session_id": session_id})
        return

    yield frame({
        "type": "thinking",
        "stage": "tool_execution",
        "content": "已获得同意，正在执行受控操作",
    })
    try:
        async with AsyncSessionLocal() as db:
            result = await execute_approved_write(db, user_id, proposal)
        # 业务服务已提交；立即封存运行，断线后不再重做。
        await finish(user_id, session_id, run_id, "completed", result)
    except Exception:
        # 不确定业务是否已提交时保留 executing，要求人工核对而不是自动重试。
        yield frame({
            "type": "error", "content": "操作状态需要核对，请勿重复点击",
        })
        yield frame({"type": "done", "session_id": session_id})
        return

    parts: list[str] = []
    try:
        async for part in deepseek_client.stream_chat([
            {
                "role": "system",
                "content": "只根据工具执行结果解释，不声称执行了其他操作。",
            },
            {
                "role": "user",
                "content": f"用户请求：{query}\n工具结果：{result}",
            },
        ], max_tokens=300):
            parts.append(part)
            yield frame({
                "type": "response", "content": part, "session_id": session_id,
            })
        answer = "".join(parts).strip() or result
        if not parts:
            yield frame({
                "type": "response", "content": answer, "session_id": session_id,
            })
        async with AsyncSessionLocal() as db:
            session = await chat_session_service.owned(db, user_id, session_id)
            await chat_session_service.append_turn(db, session, query, answer)
    except Exception:
        # 写入已经完成，回答失败不能反写成“操作失败”。
        yield frame({
            "type": "error",
            "content": "操作已完成，但回答未保存；请刷新目标页面核对",
        })
    yield frame({"type": "done", "session_id": session_id})
