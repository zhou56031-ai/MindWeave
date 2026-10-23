"""判断本地证据能否支持回答，并给出 Web 查询。"""

import json
from pathlib import Path

from pydantic import BaseModel, Field

from app.schemas.models import RetrievalHit
from app.services.deepseek_client import deepseek_client
from app.services.retrieval_policy import format_context

PROMPT = Path(__file__).resolve().parents[1] / "prompt" / "answerability.txt"
FRESHNESS = (
    "最新", "现在", "今天", "新闻", "价格", "版本",
    "latest", "today", "current",
)


class Answerability(BaseModel):
    answerable: bool
    confidence: float = Field(ge=0, le=1)
    reason: str = ""
    web_queries: list[str] = Field(default_factory=list, max_length=3)


async def evaluate(query: str, hits: list[RetrievalHit]) -> Answerability:
    if not hits:
        return Answerability(
            answerable=False,
            confidence=1.0,
            reason="没有本地证据",
            web_queries=[query[:100]],
        )
    if any(term in query.lower() for term in FRESHNESS):
        return Answerability(
            answerable=False,
            confidence=0.9,
            reason="问题需要最新信息",
            web_queries=[query[:100]],
        )
    prompt = PROMPT.read_text(encoding="utf-8")
    try:
        raw = await deepseek_client.chat([
            {
                "role": "system",
                "content": prompt.replace("{query}", query).replace(
                    "{evidence}", format_context(hits)[:5000],
                ),
            },
            {"role": "user", "content": "请判断并只返回 JSON。"},
        ], json_mode=True, max_tokens=220)
        return Answerability.model_validate(json.loads(raw))
    except Exception:
        return Answerability(
            answerable=True,
            confidence=0.55,
            reason="可答性模型失败，保留本地证据",
            web_queries=[],
        )
