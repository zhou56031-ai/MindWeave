"""SSE 适配：运行原生工具循环，保持前端事件契约。"""
import asyncio
import time
from uuid import uuid4
import json
from collections.abc import AsyncIterator
from fastapi import HTTPException
from app.agent.chat_loop import POLICY, run_loop
from app.agent.loop_protocol import TOOLS
from app.agent.run_store import approval_payload, save_pending
from app.agent.session_lease import session_lease
from app.services.chat_memory_store import ChatMemoryStore
from app.core.agent_trace import TraceBuffer, bind, emit, span, text_info
from app.core.settings import settings
from app.services.agent_trace_store import save_trace


def frame(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


async def _chat_events(
    user_id: str, query: str, session_id: str, existing_id: str | None,
) -> AsyncIterator[str]:
    try:
        async with session_lease(user_id, session_id):
            async with asyncio.timeout(180):
                store = ChatMemoryStore(user_id, session_id)
                with span("memory.start"):
                    await store.start(existing_id, query)
                with span("memory.load"):
                    context = await store.load(POLICY.read_text(encoding="utf-8"), TOOLS)
                async for event in run_loop(context, store, query):
                    if event["type"] == "proposal":
                        run = await save_pending(
                            user_id, session_id, session_id, query, event["proposal"],
                        )
                        yield frame({
                            "type": "interrupt", "session_id": session_id,
                            "run_id": run.id, "payload": approval_payload(event["proposal"]),
                        })
                    elif event["type"] == "answer":
                        with span("memory.finish"):
                            await store.finish(query, event["content"], context)
                        yield frame({"type": "response", "content": event["content"], "session_id": session_id})
                    else:
                        yield frame(event)
    except HTTPException as exc:
        yield frame({"type": "error", "content": str(exc.detail)})
    except TimeoutError:
        yield frame({"type": "error", "content": "本轮处理超时，未确认完成；请刷新会话核对"})
    except ValueError:
        yield frame({"type": "error", "content": "上下文或循环预算不足，或摘要格式不合格；请缩小问题范围"})
    except Exception:
        yield frame({"type": "error", "content": "本轮未完成，请刷新会话后重试"})
    yield frame({"type": "done", "session_id": session_id})


def _usage_snapshot(trace: TraceBuffer) -> dict:
    """把本请求所有模型调用的用量汇总，供前端展示。"""
    input_tokens = output_tokens = total_tokens = 0
    calls = 0
    for event in trace.events:
        if event.get("name") != "request.usage":
            continue
        data = event.get("data") or {}
        if data.get("error_type"):
            continue
        calls += 1
        input_tokens += int(data.get("input_tokens") or 0)
        output_tokens += int(data.get("output_tokens") or 0)
        total_tokens += int(data.get("total_tokens") or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "calls": calls,
        "duration_ms": round((time.perf_counter() - trace.started) * 1000),
    }


async def chat_events(
    user_id: str, query: str, session_id: str, existing_id: str | None,
    *, run_id: str | None = None,
) -> AsyncIterator[str]:
    if not settings.AGENT_TRACE_ENABLED:
        async for chunk in _chat_events(user_id, query, session_id, existing_id):
            yield chunk
        return
    trace = TraceBuffer(run_id or str(uuid4()), user_id, session_id)
    sources: dict[str, dict] = {}
    try:
        with bind(trace):
            emit("request.start", query=text_info(query))
            async for chunk in _chat_events(user_id, query, session_id, existing_id):
                payload = json.loads(chunk.removeprefix("data: ").strip())
                event_type = payload.get("type")
                if event_type == "thinking":
                    details = payload.get("details") or {}
                    if details.get("status") == "evidence":
                        for item in details.get("results") or []:
                            if isinstance(item, dict) and item.get("id"):
                                sources[item["id"]] = item
                if event_type == "response":
                    trace.status = "completed"
                    payload["sources"] = list(sources.values())
                    payload["usage"] = _usage_snapshot(trace)
                    emit("answer.saved", answer=text_info(payload.get("content", "")))
                elif event_type == "interrupt":
                    trace.status = "waiting_approval"
                    emit("approval.pending", approval_run_id=payload.get("run_id"))
                elif event_type == "error":
                    trace.status = "error"
                    emit("request.error", message=text_info(payload.get("content", "")))
                payload["trace_run_id"] = trace.id
                yield frame(payload)
            emit("request.end", status=trace.status)
    finally:
        await save_trace(trace)
