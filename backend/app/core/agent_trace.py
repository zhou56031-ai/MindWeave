"""请求内诊断：ContextVar 关联、父子事件与有界文本元信息。"""
import asyncio
import hashlib
import json
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from uuid import uuid4
from app.core.settings import settings

CURRENT = ContextVar("agent_trace", default=None)
PARENT = ContextVar("agent_trace_parent", default=None)
MAX_EVENTS = 200
MAX_EVENT_BYTES = 6000


def text_info(value: str) -> dict:
    result = {
        "chars": len(value),
        "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
    }
    if settings.AGENT_TRACE_INCLUDE_TEXT:
        result["preview"] = value[:400]
    return result


@dataclass
class TraceBuffer:
    id: str
    user_id: str
    session_id: str
    started: float = field(default_factory=time.perf_counter)
    status: str = "interrupted"
    events: list = field(default_factory=list)
    dropped: int = 0

    def add(self, name: str, **data) -> None:
        if len(self.events) >= MAX_EVENTS:
            self.dropped += 1
            return
        encoded = json.dumps(data, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > MAX_EVENT_BYTES:
            data = {"omitted": True, **text_info(encoded)}
        self.events.append({
            "seq": len(self.events) + 1, "name": name,
            "at_ms": round((time.perf_counter() - self.started) * 1000),
            "parent_id": PARENT.get(), "data": data,
        })

    def payload(self) -> dict:
        return {"schema_version": 1, "events": self.events, "dropped": self.dropped}


def emit(name: str, **data) -> None:
    trace = CURRENT.get()
    if trace is not None:
        trace.add(name, **data)


@contextmanager
def bind(trace: TraceBuffer):
    token = CURRENT.set(trace)
    parent_token = PARENT.set(None)
    try:
        yield
    finally:
        PARENT.reset(parent_token)
        CURRENT.reset(token)


@contextmanager
def span(name: str, **attributes):
    identifier = str(uuid4())
    result = {}
    started = time.perf_counter()
    emit(name + ".start", span_id=identifier, **attributes)
    token = PARENT.set(identifier)
    status = "ok"
    try:
        yield result
    except BaseException as exc:
        status = "cancelled" if isinstance(exc, (asyncio.CancelledError, GeneratorExit)) else "error"
        result["error_type"] = type(exc).__name__
        raise
    finally:
        PARENT.reset(token)
        emit(name + ".end", span_id=identifier, status=status,
             duration_ms=round((time.perf_counter() - started) * 1000), **result)


def observe(name: str):
    def decorate(function):
        @wraps(function)
        async def wrapper(*args, **kwargs):
            with span(name) as details:
                value = await function(*args, **kwargs)
                if isinstance(value, bool):
                    details["changed"] = value
                return value
        return wrapper
    return decorate
