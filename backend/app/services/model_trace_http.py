"""只包装非流式模型 HTTP 调用，不改变主备密钥选择。"""
import json
from app.core.agent_trace import CURRENT, span, text_info


async def post_model(client, url: str, *, headers: dict, json_body: dict, key_slot: int):
    if CURRENT.get() is None:
        return await client.post(url, headers=headers, json=json_body)
    messages = json.dumps(json_body.get("messages", []), ensure_ascii=False)
    with span("llm.http", model=json_body.get("model"), key_slot=key_slot,
              max_tokens=json_body.get("max_tokens"),
              message_count=len(json_body.get("messages", [])),
              tools_count=len(json_body.get("tools", [])), input=text_info(messages)) as details:
        response = await client.post(url, headers=headers, json=json_body)
        details["http_status"] = response.status_code
        if response.is_success:
            try:
                payload = response.json()
                usage = payload.get("usage") or {}
                details["usage"] = {
                    key: usage[key] for key in (
                        "prompt_tokens", "completion_tokens", "total_tokens",
                        "prompt_cache_hit_tokens", "prompt_cache_miss_tokens",
                    ) if isinstance(usage.get(key), int)
                }
                choice = (payload.get("choices") or [{}])[0]
                details["finish_reason"] = choice.get("finish_reason")
                details["output"] = text_info(json.dumps(choice.get("message", {}), ensure_ascii=False))
            except (ValueError, TypeError, IndexError, AttributeError):
                details["decode_error"] = True
        response.raise_for_status()
        return response
