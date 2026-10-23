"""有界 LLM 重排、来源配额与相邻片段扩展。"""
import json
from pathlib import Path
from pydantic import BaseModel, Field
from app.core.agent_trace import emit, observe
from app.core.settings import settings
from app.graph.neo4j_client import graph_driver
from app.schemas.models import RetrievalHit
from app.services.deepseek_client import deepseek_client

PROMPT = Path(__file__).resolve().parents[1] / "prompt/rerank_evidence.txt"


class RankItem(BaseModel):
    id: str
    score: int = Field(ge=0, le=3, strict=True)


class RankResult(BaseModel):
    items: list[RankItem] = Field(min_length=1, max_length=40)


def hit_key(hit: RetrievalHit):
    return (hit.source_kind, hit.source_id, hit.chunk_id or "")


@observe("rag.rerank")
async def rerank(question: str, hits: list[RetrievalHit]) -> list[RetrievalHit]:
    candidates = hits[:settings.RAG_RERANK_LIMIT]
    if not candidates:
        return []
    rows = [{"id": str(index), "title": hit.title[:150], "page": hit.page,
             "section": hit.section, "text": hit.snippet[:600]}
            for index, hit in enumerate(candidates)]
    try:
        raw = await deepseek_client.chat([
            {"role": "system", "content": PROMPT.read_text(encoding="utf-8")},
            {"role": "user", "content": json.dumps({
                "question": question[:2000], "candidates": rows,
            }, ensure_ascii=False)},
        ], json_mode=True, max_tokens=1200)
        result = RankResult.model_validate(json.loads(raw))
        expected = {str(index) for index in range(len(candidates))}
        if len(result.items) != len(expected) or {item.id for item in result.items} != expected:
            raise ValueError("重排候选集合不匹配")
        scores = {item.id: item.score for item in result.items}
        ranked = [hit.model_copy(update={"rerank_score": scores[str(index)]})
                  for index, hit in enumerate(candidates) if scores[str(index)] > 0]
        ranked.sort(key=lambda hit: -(hit.rerank_score or 0))
        emit("rag.rerank.result", mode="llm", scores=[item.model_dump() for item in result.items],
             candidate_keys=[list(hit_key(hit)) for hit in candidates])
        return ranked
    except Exception as exc:
        emit("rag.rerank.result", mode="fallback", error_type=type(exc).__name__)
        return candidates


async def expand_neighbors(user_id: str, hit: RetrievalHit) -> RetrievalHit:
    if hit.parent_text:
        return hit.model_copy(update={"snippet": hit.parent_text[:2200]})
    if not hit.chunk_id or hit.source_kind not in {"note", "knowledge_base"}:
        return hit
    try:
        rows = (await graph_driver().execute_query(
            "MATCH (seed:Chunk {user_id:$uid,id:$cid}) "
            "MATCH (c:Chunk {user_id:$uid,kind:seed.kind,source_id:seed.source_id}) "
            "WHERE abs(c.chunk_index-seed.chunk_index)<=1 "
            "AND coalesce(c.generation,'legacy')=coalesce(seed.generation,'legacy') "
            "AND (seed.page IS NULL OR c.page=seed.page) "
            "RETURN c.text AS text,c.chunk_index AS idx,seed.chunk_index AS center "
            "ORDER BY idx",
            uid=user_id, cid=hit.chunk_id,
        )).records
    except Exception:
        return hit
    if not rows:
        return hit
    parts = []
    for row in rows:
        text = row["text"] or ""
        parts.append(text[-400:] if row["idx"] < row["center"] else
                     text[:400] if row["idx"] > row["center"] else text[:1200])
    return hit.model_copy(update={"snippet": "\n\n".join(parts)[:2200]})


@observe("rag.select")
async def select_evidence(user_id: str, hits: list[RetrievalHit]) -> list[RetrievalHit]:
    selected = []
    counts = {}
    for hit in hits:
        source = (hit.source_kind, hit.source_id)
        if counts.get(source, 0) >= 2:
            continue
        selected.append(await expand_neighbors(user_id, hit))
        counts[source] = counts.get(source, 0) + 1
        if len(selected) >= settings.RAG_FINAL_LIMIT:
            break
    return selected
