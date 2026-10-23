"""模型生成与结果校验之间的边界：先容错清洗，再严格校验。"""
import json
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError

from app.graph.schemas import ExtractResult
from app.services.deepseek_client import deepseek_client

PROMPT = Path(__file__).resolve().parents[1] / "prompt" / "entity_extraction.txt"


def _sanitize(payload: dict) -> dict:
    """去重实体、丢掉悬空关系、补默认类型；只做结构清洗，不编造内容。"""
    if not isinstance(payload.get("entities"), list) or not isinstance(payload.get("relations"), list):
        raise ValueError("缺少 entities/relations 数组")
    entities, seen = [], set()
    for item in payload.get("entities") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        entities.append({
            "name": name[:120],
            "type": str(item.get("type") or "concept")[:50],
            "description": str(item.get("description") or "")[:500],
        })
    canonical = {item["name"]: item["name"] for item in entities}
    folded = {name.casefold(): name for name in canonical}
    relations = []
    for item in payload.get("relations") or []:
        if not isinstance(item, dict):
            continue
        source = folded.get(str(item.get("source", "")).strip().casefold())
        target = folded.get(str(item.get("target", "")).strip().casefold())
        if not source or not target or source == target:
            continue
        relations.append({
            "source": source, "target": target,
            "relation_type": str(item.get("relation_type") or "关联")[:50],
        })
    return {"entities": entities[:30], "relations": relations[:60]}


async def _extract_once(source: str, max_tokens: int) -> dict | None:
    raw = await deepseek_client.chat([
        {"role": "system", "content": PROMPT.read_text(encoding="utf-8")},
        {"role": "user", "content": source},
    ], json_mode=True, max_tokens=max_tokens)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


async def extract_entities(text: str) -> ExtractResult:
    source = text.strip()[:6000]
    if not source:
        return ExtractResult()
    attempts = [(source[:6000], 2000), (source[:2800], 1600)]
    last_error: Exception | None = None
    for chunk, budget in attempts:
        try:
            data = await _extract_once(chunk, budget)
            if data is None:
                continue
            return ExtractResult.model_validate(_sanitize(data))
        except (HTTPException, ValidationError, ValueError) as exc:
            last_error = exc
            continue
    raise HTTPException(status_code=502, detail="实体关系结果不符合要求") from last_error
