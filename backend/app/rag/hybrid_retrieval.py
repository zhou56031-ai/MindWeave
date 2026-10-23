"""扩大双路候选，保留片段身份；异常时使用 MySQL 降级。"""
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.agent_trace import emit
from app.core.settings import settings
from app.graph.neo4j_client import graph_driver
from app.rag.embedding import embed
from app.rag.fusion import escape_lucene, fuse
from app.schemas.models import RetrievalHit
from app.services.knowledge_retrieval import knowledge_retrieval
from app.services.retrieval_policy import normalize_query, short_snippet


async def search(db: AsyncSession, user_id: str, query: str) -> list[RetrievalHit]:
    keyword = normalize_query(query)
    try:
        vector = await embed(keyword)
        driver = graph_driver()
        candidates = min(settings.RAG_RECALL_LIMIT * 10, settings.RAG_VECTOR_OVERFETCH)
        vector_rows = (await driver.execute_query(
            "CALL db.index.vector.queryNodes('chunk_embedding_index', $n, $vector) "
            "YIELD node, score WHERE node.user_id=$uid "
            "RETURN node.id AS id,node.kind AS kind,node.source_id AS sid,"
            "node.source_name AS title,node.text AS text,node.page AS page,"
            "node.section AS section,node.chunk_index AS chunk_index,"
            "node.parent_id AS parent_id,node.parent_text AS parent_text",
            n=candidates, vector=vector, uid=user_id,
        )).records
        word_rows = (await driver.execute_query(
            "CALL db.index.fulltext.queryNodes('chunk_text_index', $q, {limit:$n}) "
            "YIELD node, score WHERE node.user_id=$uid "
            "RETURN node.id AS id,node.kind AS kind,node.source_id AS sid,"
            "node.source_name AS title,node.text AS text,node.page AS page,"
            "node.section AS section,node.chunk_index AS chunk_index,"
            "node.parent_id AS parent_id,node.parent_text AS parent_text",
            n=candidates, q=escape_lucene(keyword), uid=user_id,
        )).records
    except Exception as exc:
        emit("rag.fallback", error_type=type(exc).__name__, target="mysql")
        return await knowledge_retrieval.search(db, user_id, keyword)

    ranked = fuse(
        [
            ("vector", [row.data() for row in vector_rows]),
            ("fulltext", [row.data() for row in word_rows]),
        ],
        limit=settings.RAG_RECALL_LIMIT,
        quotas={
            "vector": settings.RAG_VECTOR_QUOTA,
            "fulltext": settings.RAG_FULLTEXT_QUOTA,
        },
    )
    emit(
        "rag.recall",
        vector_count=len(vector_rows),
        fulltext_count=len(word_rows),
        selected=len(ranked),
        fused_sources={key: row["sources"] for key, (_, row) in enumerate(ranked)},
    )
    return [RetrievalHit(
        source_kind="note" if row["kind"] == "note" else "knowledge_base",
        source_id=row["sid"], title=row["title"] or "",
        snippet=short_snippet(row["text"] or "", keyword), score=points,
        chunk_id=row["id"], chunk_index=row.get("chunk_index"),
        page=row.get("page"), section=row.get("section"),
        parent_text=row.get("parent_text"),
    ) for points, row in ranked]
