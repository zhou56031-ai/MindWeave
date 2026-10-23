"""系统类型与孤儿实体维护。"""

from app.graph.neo4j_client import graph_driver

SYSTEM_TYPES = (
    ("concept", "概念", "#64748B"),
    ("person", "人物", "#2563EB"),
    ("organization", "组织", "#7C3AED"),
    ("technology", "技术", "#059669"),
)


async def ensure_system_types(user_id: str) -> None:
    for name, display, color in SYSTEM_TYPES:
        await graph_driver().execute_query(
            "MERGE (t:EntityType {user_id:$uid,name:$name}) "
            "ON CREATE SET t.id=randomUUID() "
            "SET t.display_name=$display,t.color=$color,t.is_system=true",
            uid=user_id,
            name=name,
            display=display,
            color=color,
        )


async def cleanup_orphan_entities(user_id: str, entity_ids: list[str]) -> int:
    if not entity_ids:
        return 0
    rows = (await graph_driver().execute_query(
        "MATCH (e:Entity {user_id:$uid}) WHERE e.id IN $ids "
        "AND coalesce(e.manual,false)=false "
        "AND NOT (e)<-[:MENTIONS]-(:Source {user_id:$uid}) "
        "AND NOT (e)<-[:MENTIONS]-(:Chunk {user_id:$uid}) "
        "DETACH DELETE e RETURN count(e) AS removed",
        uid=user_id,
        ids=entity_ids,
    )).records
    return int(rows[0]["removed"]) if rows else 0
