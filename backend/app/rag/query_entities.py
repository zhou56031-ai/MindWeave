"""从问句提取图谱实体候选，失败时使用规则分词。"""

import json
import re
from pathlib import Path

from app.services.deepseek_client import deepseek_client

PROMPT = Path(__file__).resolve().parents[1] / "prompt" / "query_entities.txt"
NOISE = {
    "是什么", "有哪些", "关系", "相关", "介绍", "请问", "怎么", "如何",
    "what", "who", "is", "are", "the",
}


def fallback_candidates(query: str) -> list[str]:
    parts = re.split(r"[\s,，。！？!?、;；:：/（）()]+", query)
    result = []
    for part in parts:
        value = part.strip()
        if value and value.lower() not in NOISE and value not in result:
            result.append(value)
    return result[:5]


async def extract_query_entities(query: str) -> list[str]:
    try:
        raw = await deepseek_client.chat([
            {"role": "system", "content": PROMPT.read_text(encoding="utf-8")},
            {"role": "user", "content": query[:1000]},
        ], json_mode=True, max_tokens=120)
        payload = json.loads(raw)
        if isinstance(payload, list):
            values = [
                item.strip() for item in payload
                if isinstance(item, str) and item.strip()
            ]
            if values:
                return list(dict.fromkeys(values))[:5]
    except Exception:
        pass
    return fallback_candidates(query)
