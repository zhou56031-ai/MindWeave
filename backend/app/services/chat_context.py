"""可恢复的工作上下文：原生工具消息、旧结果缩减、结构化摘要。"""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated
from pydantic import BaseModel, Field
from app.core.settings import settings
from app.services.deepseek_client import deepseek_client
from app.core.agent_trace import emit, observe, text_info

SUMMARY_PROMPT = Path(__file__).resolve().parents[1] / "prompt/context_summary.txt"
ShortText = Annotated[str, Field(max_length=180)]


class MemorySummary(BaseModel):
    goal: str = Field(max_length=300)
    constraints: list[ShortText] = Field(max_length=10)
    facts: list[ShortText] = Field(max_length=10)
    completed: list[ShortText] = Field(max_length=10)
    open_questions: list[ShortText] = Field(max_length=10)
    sources: list[ShortText] = Field(max_length=10)


def serialize(value) -> str:
    return json.dumps(value, ensure_ascii=False)


@dataclass
class AgentContext:
    messages: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    archives: list[str] = field(default_factory=list)

    def dump(self) -> dict:
        return {"messages": self.messages, "summary": self.summary, "archives": self.archives}

    def request_messages(self, system: str) -> list[dict]:
        memory = []
        if self.summary:
            memory = [{"role": "user", "content": serialize({
                "kind": "historical_summary_reference_only",
                "summary": self.summary, "archives": self.archives,
            })}]
        return [{"role": "system", "content": system}, *memory, *self.messages]

    def input_bytes(self, system: str, tools: list[dict]) -> int:
        return len(serialize({
            "messages": self.request_messages(system), "tools": tools,
        }).encode("utf-8"))

    @observe("context.prepare")
    async def prepare(self, system: str, tools: list[dict], archive, *, force=False) -> bool:
        emit("context.budget", input_bytes=self.input_bytes(system, tools), force=force)
        limit = settings.AGENT_INPUT_BYTES
        if not force and self.input_bytes(system, tools) <= limit:
            return False
        changed = False
        # 每次只有一个新结果；最新两个结果至少有一次机会被模型阅读。
        results = [m for m in self.messages if m.get("role") == "tool"]
        for message in results[:-2]:
            if not force and self.input_bytes(system, tools) <= limit:
                return changed
            try:
                payload = json.loads(message["content"])
            except (ValueError, TypeError):
                continue
            artifact_id = payload.get("artifact_id") if isinstance(payload, dict) else None
            if artifact_id and "preview" in payload:
                message["content"] = serialize({
                    "artifact_id": artifact_id,
                    "status": "archived; use read_artifact for exact content",
                })
                emit("context.tool_shrunk", artifact_id=artifact_id)
                changed = True
        if not force and self.input_bytes(system, tools) <= limit:
            return changed
        starts = [i for i, m in enumerate(self.messages) if m.get("role") == "user"]
        if len(starts) < 3:
            if self.input_bytes(system, tools) > limit:
                raise ValueError("当前必要上下文超过预算，请缩小问题范围")
            return changed
        cut = starts[-2]
        archive_id = await archive("transcript", serialize(self.dump()))
        old = serialize(self.messages[:cut])
        summary = self.summary
        # 摘要调用也限制输入；长原文分片渐进合并，而非一次塞入摘要模型。
        for offset in range(0, len(old), 6000):
            raw = await deepseek_client.chat([
                {"role": "system", "content": SUMMARY_PROMPT.read_text(encoding="utf-8")},
                {"role": "user", "content": serialize({
                    "previous_summary": summary,
                    "fragment": old[offset:offset + 6000],
                    "fragment_offset": offset,
                    "archive_id": archive_id,
                })},
            ], json_mode=True, max_tokens=2048)
            candidate = MemorySummary.model_validate(json.loads(raw)).model_dump()
            if len(serialize(candidate).encode("utf-8")) > 16000:
                raise ValueError("摘要过大，保留原上下文")
            summary = candidate
        candidate_context = AgentContext(
            messages=self.messages[cut:], summary=summary,
            archives=[*self.archives, archive_id][-4:],
        )
        if candidate_context.input_bytes(system, tools) > limit:
            raise ValueError("摘要后仍超过预算，保留原上下文")
        self.messages = candidate_context.messages
        self.summary = summary
        self.archives = candidate_context.archives
        emit("context.compacted", archive_id=archive_id,
             input_bytes=self.input_bytes(system, tools), summary=text_info(serialize(summary)))
        return True


# 第 66 篇兼容入口；新聊天主流程使用上方 AgentContext。
POLICY = Path(__file__).resolve().parents[1] / "prompt" / "answer_policy.txt"


def bounded_history(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    pairs = []
    pending = None
    for message in messages:
        role = message.get("role")
        content = message.get("content", "")
        if not isinstance(content, str) or not content.strip():
            continue
        if role == "user":
            pending = {"role": "user", "content": content[:3000]}
        elif role == "assistant" and pending is not None:
            pairs.append([pending, {"role": "assistant", "content": content[:3000]}])
            pending = None
    selected = []
    remaining = 12000
    for pair in reversed(pairs[-6:]):
        cost = sum(len(message["content"]) for message in pair)
        if cost > remaining:
            break
        selected.append(pair)
        remaining -= cost
    return [message for pair in reversed(selected) for message in pair]


def tool_evidence(decision: dict) -> str:
    evidence = []
    for observation in decision.get("observations", []):
        name = observation.get("tool")
        result = observation.get("result")
        if name in {"none", "create_note", "mark_reviewed"} or not result:
            continue
        evidence.append({"tool": name, "result": str(result)[:2000]})
    return json.dumps(evidence[-5:], ensure_ascii=False)


def answer_messages(
    history: list[dict[str, str]], query: str,
    tools: str, context: str, used_web: bool,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": POLICY.read_text(encoding="utf-8")},
        *bounded_history(history),
        {"role": "user", "content": json.dumps({
            "question": query,
            "tool_evidence": tools,
            "retrieved_evidence": context,
            "has_web_evidence": used_web,
        }, ensure_ascii=False)},
    ]
