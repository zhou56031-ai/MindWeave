"""规划 → 片段级合并 → 相关性重排 → 邻居扩展 → 有界证据。"""
import json
from pathlib import Path
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.agent_trace import emit, observe, text_info
from app.core.settings import settings
from app.rag.answerability import Answerability, evaluate
from app.rag.graph_retrieval import search_graph
from app.rag.hybrid_retrieval import search
from app.rag.web_search import search_web
from app.rag.evidence_selection import hit_key, rerank, select_evidence
from app.schemas.models import RetrievalHit
from app.services.deepseek_client import deepseek_client
from app.services.retrieval_policy import budget_evidence, format_context

PLAN = Path(__file__).resolve().parents[1] / "prompt/retrieval_plan.txt"


class QueryPlan(BaseModel):
    resolved_question: str | None = Field(default=None, max_length=2000)
    queries: list[str] = Field(min_length=1, max_length=3)


@observe("rag.collect")
async def collect_evidence(
    db: AsyncSession, user_id: str, question: str,
    *, history: list[dict[str, str]] | None = None,
) -> tuple[list[RetrievalHit], str, Answerability, bool]:
    queries = [question[:100].strip()]
    resolved_question = question
    try:
        raw = await deepseek_client.chat([
            {"role": "system", "content": PLAN.read_text(encoding="utf-8")},
            *(history or []), {"role": "user", "content": question[:2000]},
        ], json_mode=True, max_tokens=700)
        plan = QueryPlan.model_validate(json.loads(raw))
        resolved_question = (plan.resolved_question or question).strip() or question
        cleaned = list(dict.fromkeys(q.strip() for q in plan.queries if 0 < len(q.strip()) <= 100))[:3]
        if cleaned:
            queries = cleaned
    except Exception as exc:
        emit("rag.plan.fallback", error_type=type(exc).__name__)
    emit("rag.plan", question=text_info(resolved_question), queries=[text_info(q) for q in queries])
    unique = {}
    for query in queries:
        for hit in [*(await search_graph(user_id, query)), *(await search(db, user_id, query))]:
            key = hit_key(hit)
            if key not in unique or hit.score > unique[key].score:
                unique[key] = hit
    candidates = sorted(unique.values(), key=lambda h: (-h.score, hit_key(h)))[:settings.RAG_RECALL_LIMIT]
    emit("rag.candidates", count=len(candidates))
    for rank, hit in enumerate(candidates, start=1):
        emit("rag.candidate", rank=rank, key=list(hit_key(hit)), score=hit.score,
             snippet=text_info(hit.snippet))
    ranked = await rerank(resolved_question, candidates)
    local = budget_evidence(await select_evidence(user_id, ranked))
    answerability = await evaluate(resolved_question, local)
    web = []
    if not answerability.answerable:
        for query in answerability.web_queries or [resolved_question[:100]]:
            web.extend(await search_web(query))
    # 交错放入网页证据，避免本地材料先吃光预算，真正的外部结果无法进入。
    mixed = []
    for index in range(max(len(local), min(len(web), 3))):
        if index < len(local):
            mixed.append(local[index])
        if index < min(len(web), 3):
            mixed.append(web[index])
    unique = {}
    for hit in mixed:
        unique.setdefault(hit_key(hit), hit)
    hits = budget_evidence(list(unique.values())[:10])
    context = format_context(hits)
    used_web = any(hit.source_kind == "web" for hit in hits)
    emit("rag.evidence", answerable=answerability.answerable, used_web=used_web,
         sources=[{"key": list(hit_key(hit)), "page": hit.page, "url": hit.url,
                   "rerank_score": hit.rerank_score, "snippet": text_info(hit.snippet)} for hit in hits],
         model_context=text_info(context))
    return hits, context, answerability, used_web
