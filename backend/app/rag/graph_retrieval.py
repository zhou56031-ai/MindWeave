"""按当前用户查询实体、关系来源和关联 Chunk。"""

from app.graph.neo4j_client import graph_driver
from app.rag.query_entities import extract_query_entities
from app.schemas.models import RetrievalHit
from app.services.retrieval_policy import short_snippet


async def search_graph(
    user_id: str,
    query: str,
    limit: int = 5,
) -> list[RetrievalHit]:
    names = await extract_query_entities(query)
    if not names:
        return []
    try:
        rows = (await graph_driver().execute_query(
            "MATCH (e:Entity {user_id:$uid}) "
            "WHERE any(name IN $names WHERE toLower(e.name) CONTAINS toLower(name)) "
            "OPTIONAL MATCH (s:Source {user_id:$uid})-[:MENTIONS]->(e) "
            "RETURN e.id AS id,e.name AS name,e.entity_type AS etype,"
            "e.description AS description,collect(DISTINCT s.title) AS sources "
            "LIMIT $limit",
            uid=user_id, names=names, limit=limit,
        )).records
    except Exception:
        return []

    hits = []
    for row in rows:
        detail = row["description"] or ""
        if row["etype"]:
            detail += f"\n类型：{row['etype']}"
        sources = [value for value in row["sources"] if value]
        if sources:
            detail += "\n来源：" + "、".join(sources)
        hits.append(RetrievalHit(
            source_kind="graph",
            source_id=row["id"],
            title=row["name"],
            snippet=detail.strip() or row["name"],
            score=1000,
        ))

    try:
        chunks = (await graph_driver().execute_query(
            "MATCH (e:Entity {user_id:$uid})<-[:MENTIONS]-(s:Source {user_id:$uid}) "
            "WHERE any(name IN $names WHERE toLower(e.name) CONTAINS toLower(name)) "
            "MATCH (c:Chunk {user_id:$uid,kind:s.kind,source_id:s.id}) "
            "RETURN DISTINCT c.id AS id,c.kind AS kind,c.source_id AS sid,"
            "c.source_name AS title,c.text AS text LIMIT 20",
            uid=user_id, names=names,
        )).records
    except Exception:
        return hits

    for row in chunks:
        hits.append(RetrievalHit(
            source_kind="note" if row["kind"] == "note" else "knowledge_base",
            source_id=row["sid"],
            title=row["title"] or "",
            snippet=short_snippet(row["text"] or "", names[0]),
            score=800,
        ))
    return hits
