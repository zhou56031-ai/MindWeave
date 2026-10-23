"""DeepSeek Chat Completions 的统一异步 HTTP 边界。"""

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
from fastapi import HTTPException

from app.core.agent_trace import emit
from app.core.settings import settings
from app.agent.loop_protocol import AssistantTurn, ContextLimitError
from app.services.model_trace_http import post_model

FALLBACK_HTTP_STATUSES = {401, 402, 429, 500, 502, 503, 504}


def _api_keys() -> list[str]:
    """按优先级取密钥；两项相同时避免重复请求。"""
    primary = settings.DEEPSEEK_API_KEY.get_secret_value().strip()
    backup = settings.DEEPSEEK_API_KEY_BACKUP.get_secret_value().strip()
    keys = list(dict.fromkeys(key for key in (primary, backup) if key))
    if not keys:
        raise HTTPException(status_code=503, detail="模型服务未配置")
    return keys


def _can_try_backup(error: httpx.HTTPError) -> bool:
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in FALLBACK_HTTP_STATUSES
    # 连接尚未建立时切换不会把两段模型输出拼在一起。
    return isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout))



def _emit_usage(response, *, body_bytes: int, key_slot: int) -> None:
    """记录每次模型调用的真实用量；失败请求由调用方补一条零用量。"""
    try:
        usage = response.json().get("usage") or {}
    except Exception:
        usage = {}
    emit(
        "request.usage",
        model=settings.DEEPSEEK_MODEL,
        input_tokens=usage.get("prompt_tokens"),
        output_tokens=usage.get("completion_tokens"),
        total_tokens=usage.get("total_tokens"),
        input_bytes=body_bytes,
        key_slot=key_slot,
    )
    emit(
        "context.budget",
        input_bytes=body_bytes,
        input_tokens=usage.get("prompt_tokens"),
        budget_bytes=settings.AGENT_INPUT_BYTES,
    )


class DeepSeekClient:
    async def complete_turn(self, messages: list[dict], tools: list[dict]) -> dict:
        keys = _api_keys()
        body = {
            "model": settings.DEEPSEEK_MODEL,
            "messages": messages, "tools": tools,
            "tool_choice": "auto", "parallel_tool_calls": False,
            "stream": False, "thinking": {"type": "disabled"},
            "max_tokens": settings.AGENT_OUTPUT_TOKENS,
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=5)) as client:
            for index, key in enumerate(keys):
                try:
                    response = await post_model(
                        client, settings.DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions",
                        headers={"Authorization": f"Bearer {key}"},
                        json_body=body, key_slot=index,
                    )
                    response.raise_for_status()
                    break
                except httpx.HTTPError as exc:
                    if index + 1 >= len(keys) or not _can_try_backup(exc):
                        emit("request.usage", error_type=type(exc).__name__,
                             input_tokens=None, output_tokens=0)
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {400, 413}:
                        error_text = exc.response.text.lower()
                        if any(word in error_text for word in (
                            "context_length_exceeded", "maximum context length",
                            "context window exceeded", "prompt_too_long",
                        )):
                            raise ContextLimitError("模型拒绝过长上下文") from exc
                    if index + 1 < len(keys) and _can_try_backup(exc):
                        continue
                    raise HTTPException(503, "Agent 模型调用失败") from exc
        _emit_usage(
            response,
            body_bytes=len(json.dumps(body, ensure_ascii=False).encode("utf-8")),
            key_slot=index,
        )
        try:
            choice = response.json()["choices"][0]
            reason = choice.get("finish_reason")
            raw_message = choice["message"]
            turn = AssistantTurn.model_validate({
                **raw_message, "tool_calls": raw_message.get("tool_calls") or [],
            })
            expected = "tool_calls" if turn.tool_calls else "stop"
            if reason != expected or (not turn.tool_calls and not (turn.content or "").strip()):
                raise ValueError("模型未完整结束本轮")
            return turn.message()
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise HTTPException(502, "Agent 响应协议异常或被截断") from exc

    async def stream_chat(
        self, messages: Sequence[dict[str, Any]], *, max_tokens: int | None = None
    ) -> AsyncIterator[str]:
        if max_tokens is None:
            max_tokens = settings.CHAT_ANSWER_MAX_TOKENS
        keys = _api_keys()
        if not messages or max_tokens < 1 or max_tokens > 4096:
            raise ValueError("模型消息或输出上限不合法")
        timeout = httpx.Timeout(75.0, connect=5.0, read=60.0, write=10.0, pool=5.0)
        body = {
            "model": settings.DEEPSEEK_MODEL,
            "messages": list(messages),
            "max_tokens": max_tokens,
            "stream": True,
            # 当前模型默认先消耗额度生成 reasoning_content；短回答使用非思考模式。
            "thinking": {"type": "disabled"},
        }
        for index, key in enumerate(keys):
            finished = False
            emitted = False
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream(
                        "POST", settings.DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions",
                        headers={"Authorization": f"Bearer {key}"}, json=body,
                    ) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            payload = line[6:]
                            if payload == "[DONE]":
                                finished = True
                                break
                            try:
                                choice = json.loads(payload)["choices"][0]
                                if choice.get("finish_reason") == "length":
                                    raise HTTPException(status_code=502, detail="模型流输出被截断")
                                delta = choice["delta"].get("content")
                            except (ValueError, KeyError, IndexError, TypeError) as exc:
                                raise HTTPException(status_code=502, detail="模型流格式异常") from exc
                            if isinstance(delta, str) and delta:
                                emitted = True
                                yield delta
            except httpx.HTTPError as exc:
                if index + 1 < len(keys) and not emitted and _can_try_backup(exc):
                    continue
                raise HTTPException(status_code=503, detail="模型流暂不可用") from exc
            if not finished:
                raise HTTPException(status_code=502, detail="模型流未正常结束")
            return

    async def chat(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        json_mode: bool = False,
        max_tokens: int = 512,
    ) -> str:
        keys = _api_keys()
        if not messages or max_tokens < 1 or max_tokens > 4096:
            raise ValueError("模型消息或输出上限不合法")

        body: dict[str, Any] = {
            "model": settings.DEEPSEEK_MODEL,
            "messages": list(messages),
            "max_tokens": max_tokens,
            "stream": False,
            "thinking": {"type": "disabled"},
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        timeout = httpx.Timeout(30.0, connect=5.0, read=30.0, write=10.0, pool=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            for index, key in enumerate(keys):
                try:
                    response = await post_model(
                        client, settings.DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions",
                        headers={"Authorization": f"Bearer {key}"},
                        json_body=body, key_slot=index,
                    )
                    response.raise_for_status()
                    break
                except httpx.HTTPError as exc:
                    if index + 1 < len(keys) and _can_try_backup(exc):
                        continue
                    emit("request.usage", error_type=type(exc).__name__,
                         input_tokens=None, output_tokens=0)
                    raise HTTPException(status_code=503, detail="模型服务暂不可用") from exc

        _emit_usage(
            response,
            body_bytes=len(json.dumps(body, ensure_ascii=False).encode("utf-8")),
            key_slot=index,
        )
        try:
            choice = response.json()["choices"][0]
            if choice.get("finish_reason") == "length":
                raise HTTPException(status_code=502, detail="模型输出被截断")
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=502, detail="模型响应格式异常") from exc
        if not isinstance(content, str) or not content.strip():
            raise HTTPException(status_code=502, detail="模型没有返回文字")
        return content.strip()


deepseek_client = DeepSeekClient()
