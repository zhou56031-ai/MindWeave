"""把用户范围内的图记录转换成前端 GraphView。"""
from app.graph.neo4j_client import graph_driver


async def graph_view(
    user_id: str, *, source_kind: str | None = None,
    source_id: str | None = None, entity_types: list[str] | None = None,
    limit: int = 50,
) -> dict:
    if source_kind is not None and source_kind not in {"note", "doc"}:
        raise ValueError("来源类型不支持")
    query = (
        "MATCH (s:Source {user_id:$uid})-[:MENTIONS]->(e:Entity {user_id:$uid}) "
        "WHERE ($kind IS NULL OR s.kind=$kind) AND ($sid IS NULL OR s.id=$sid) "
        "AND ($types IS NULL OR e.entity_type IN $types) "
        "RETURN s.id AS sid,s.kind AS kind,s.title AS title,"
        "e.id AS eid,e.name AS name,e.entity_type AS etype LIMIT $limit"
    )
    rows = (await graph_driver().execute_query(
        query, uid=user_id, kind=source_kind, sid=source_id,
        types=entity_types or None, limit=limit,
    )).records
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    entity_ids = []
    for row in rows:
        nodes[row["sid"]] = {
            "id": row["sid"], "label": row["title"] or row["sid"],
            "node_type": row["kind"],
        }
        nodes[row["eid"]] = {
            "id": row["eid"], "label": row["name"],
            "node_type": "entity", "entity_type_id": row["etype"],
        }
        entity_ids.append(row["eid"])
        edges.append({
            "id": "mention:" + row["sid"] + ":" + row["eid"],
            "source": row["sid"], "target": row["eid"],
            "kind": "relation", "relation_type": "mentions",
        })
    if source_kind is None and source_id is None:
        manual_entities = (await graph_driver().execute_query(
            "MATCH (e:Entity {user_id:$uid,manual:true}) "
            "WHERE ($types IS NULL OR e.entity_type IN $types) "
            "RETURN e.id AS eid,e.name AS name,e.entity_type AS etype LIMIT $limit",
            uid=user_id, types=entity_types or None, limit=limit,
        )).records
        for row in manual_entities:
            nodes[row["eid"]] = {
                "id": row["eid"], "label": row["name"],
                "node_type": "entity", "entity_type_id": row["etype"],
            }
            entity_ids.append(row["eid"])
    if entity_ids:
        related = (await graph_driver().execute_query(
            "MATCH (a:Entity {user_id:$uid})-[r:RELATED {user_id:$uid}]->"
            "(b:Entity {user_id:$uid}) "
            "WHERE a.id IN $ids AND b.id IN $ids "
            "RETURN a.id AS aid,b.id AS bid,r.relation_type AS kind,"
            "r.source_id AS source_id LIMIT 300",
            uid=user_id, ids=list(set(entity_ids)),
        )).records
        edges.extend({
            "id": "relation:" + r["aid"] + ":" + r["bid"] + ":"
            + r["source_id"] + ":" + r["kind"],
            "source": r["aid"], "target": r["bid"],
            "kind": "relation", "relation_type": r["kind"],
        } for r in related)
        manual_rows = (await graph_driver().execute_query(
            "MATCH (a:Entity {user_id:$uid})-[r:MANUAL_RELATION {user_id:$uid}]->"
            "(b:Entity {user_id:$uid}) "
            "WHERE a.id IN $ids AND b.id IN $ids "
            "RETURN r.id AS id,a.id AS aid,b.id AS bid,"
            "r.relation_type AS kind LIMIT 300",
            uid=user_id, ids=list(set(entity_ids)),
        )).records
        edges.extend({
            "id": "manual_relation:" + r["id"],
            "source": r["aid"], "target": r["bid"],
            "kind": "relation", "relation_type": r["kind"],
        } for r in manual_rows)
        wiki_rows = (await graph_driver().execute_query(
            "MATCH (a:Note {user_id:$uid})-[r:WIKI {user_id:$uid}]->"
            "(b:Note {user_id:$uid}) "
            "RETURN a.id AS aid,a.title AS atitle,"
            "b.id AS bid,b.title AS btitle LIMIT 300",
            uid=user_id,
        )).records
        for row in wiki_rows:
            nodes[row["aid"]] = {
                "id": row["aid"],
                "label": row["atitle"] or row["aid"],
                "node_type": "note",
            }
            nodes[row["bid"]] = {
                "id": row["bid"],
                "label": row["btitle"] or row["bid"],
                "node_type": "note",
            }
            edges.append({
                "id": f"wiki:{row['aid']}:{row['bid']}",
                "source": row["aid"],
                "target": row["bid"],
                "kind": "wiki",
                "relation_type": "wiki",
            })
    return {"nodes": list(nodes.values()), "edges": edges}


async def entity_detail(user_id: str, entity_id: str) -> dict | None:
    rows = (await graph_driver().execute_query(
        "MATCH (e:Entity {user_id:$uid,id:$eid}) "
        "OPTIONAL MATCH (s:Source {user_id:$uid})-[:MENTIONS]->(e) "
        "RETURN e.id AS id,e.name AS name,e.entity_type AS etype,"
        "e.description AS description,coalesce(e.display_name,e.name) AS display_name,"
        "coalesce(e.aliases,[]) AS aliases,coalesce(e.manual,false) AS manual,"
        "collect(DISTINCT s.id) AS source_ids",
        uid=user_id, eid=entity_id,
    )).records
    if not rows:
        return None
    row = rows[0]
    return {
        "id": row["id"], "name": row["name"], "display_name": row["display_name"],
        "type_id": row["etype"], "description": row["description"],
        "aliases": row["aliases"], "confidence": 1.0 if row["manual"] else 0.0,
        "source_note_ids": [value for value in row["source_ids"] if value],
    }


async def entity_sources(user_id: str, entity_id: str) -> list[dict]:
    rows = (await graph_driver().execute_query(
        "MATCH (s:Source {user_id:$uid})-[:MENTIONS]->"
        "(e:Entity {user_id:$uid,id:$eid}) "
        "RETURN s.id AS sid,s.kind AS kind,s.title AS title",
        uid=user_id, eid=entity_id,
    )).records
    return [{
        "entity_id": entity_id, "note_id": row["sid"],
        "source_type": row["kind"], "source_name": row["title"],
        "mention_count": 1, "context": [],
    } for row in rows]
