"""保留完整来源标头，按片段预算整理模型证据。"""
from fastapi import HTTPException
from app.core.settings import settings
from app.schemas.models import RetrievalHit

MAX_QUERY = 100
MAX_SNIPPET = 800
MAX_CONTEXT = 6000  # 旧导入兼容；新 format_context 使用配置预算。


def normalize_query(query: str) -> str:
    value = query.strip()
    if not value or len(value) > MAX_QUERY:
        raise HTTPException(status_code=422, detail="问题长度必须为 1 到 100 字符")
    return value


def short_snippet(content: str, keyword: str) -> str:
    pos = content.casefold().find(keyword.casefold())
    start = max(pos - 120, 0) if pos >= 0 else 0
    return content[start:start + MAX_SNIPPET]


def budget_evidence(hits: list[RetrievalHit]) -> list[RetrievalHit]:
    remaining = settings.RAG_CONTEXT_CHARS
    selected = []
    for hit in hits:
        label = evidence_header(hit)
        allowance = min(2200, remaining - len(label) - 4)
        if allowance < 200:
            break
        snippet = hit.snippet[:allowance]
        if not snippet.strip():
            continue
        selected.append(hit.model_copy(update={"snippet": snippet}))
        remaining -= len(label) + len(snippet) + 4
    return selected


def evidence_header(hit: RetrievalHit) -> str:
    location = {"source": f"{hit.source_kind}:{hit.source_id}", "title": hit.title[:160]}
    if hit.chunk_id:
        location["chunk_id"] = hit.chunk_id
    if hit.page is not None:
        location["page"] = hit.page
    if hit.section:
        location["section"] = hit.section[:180]
    if hit.url:
        location["url"] = hit.url[:1000]
    import json
    return "[来源 " + json.dumps(location, ensure_ascii=False) + "]"


def format_context(hits: list[RetrievalHit]) -> str:
    return "\n\n".join(
        evidence_header(hit) + "\n" + hit.snippet for hit in budget_evidence(hits)
    )
