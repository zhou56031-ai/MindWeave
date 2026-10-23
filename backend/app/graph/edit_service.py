"""仅在当前用户子图里执行人工编辑。"""

from uuid import uuid4

from fastapi import HTTPException

from app.graph.edit_schemas import EntityIn, RelationIn, TypeIn
from app.graph.neo4j_client import graph_driver


def one(records, message="图对象不存在"):
    if not records:
        raise HTTPException(status_code=404, detail=message)
    record = records[0]
    return record.data() if hasattr(record, "data") else record


async def create_entity(user_id: str, payload: EntityIn) -> dict:
    eid = str(uuid4())
    rows = (await graph_driver().execute_query(
        "CREATE (e:Entity {id:$id,user_id:$uid,name:$name,display_name:$display,"
        "entity_type:$etype,description:$description,aliases:$aliases,manual:true}) "
        "RETURN e.id AS id,e.name AS name,e.display_name AS display_name,"
        "e.entity_type AS type_id,e.description AS description,e.aliases AS aliases",
        id=eid, uid=user_id, name=payload.name,
        display=payload.display_name or payload.name,
        etype=payload.type_id, description=payload.description or "",
        aliases=payload.aliases,
    )).records
    return {**one(rows), "confidence": 1.0, "source_note_ids": []}


async def update_entity(user_id: str, entity_id: str, payload: EntityIn) -> dict:
    rows = (await graph_driver().execute_query(
        "MATCH (e:Entity {id:$id,user_id:$uid}) "
        "SET e.display_name=$display,e.entity_type=$etype,"
        "e.description=$description,e.aliases=$aliases "
        "RETURN e.id AS id,e.name AS name,e.display_name AS display_name,"
        "e.entity_type AS type_id,e.description AS description,e.aliases AS aliases",
        id=entity_id, uid=user_id, display=payload.display_name or payload.name,
        etype=payload.type_id, description=payload.description or "",
        aliases=payload.aliases,
    )).records
    return {**one(rows), "confidence": 1.0, "source_note_ids": []}


async def delete_entity(user_id: str, entity_id: str) -> None:
    rows = (await graph_driver().execute_query(
        "MATCH (e:Entity {id:$id,user_id:$uid}) "
        "WITH e,e.id AS found DETACH DELETE e RETURN found",
        id=entity_id, uid=user_id,
    )).records
    one(rows)


async def merge_entities(user_id: str, target_id: str, source_id: str) -> dict:
    if target_id == source_id:
        raise HTTPException(status_code=422, detail="不能合并同一实体")
    driver = graph_driver()
    async with driver.session() as session:
        async with await session.begin_transaction() as tx:
            result = await tx.run(
                "MATCH (t:Entity {id:$tid,user_id:$uid}),"
                "(s:Entity {id:$sid,user_id:$uid}) RETURN t.id AS tid",
                tid=target_id, sid=source_id, uid=user_id,
            )
            rows = await result.data()
            one(rows)
            await tx.run(
                "MATCH (n:Source {user_id:$uid})-[m:MENTIONS]->"
                "(s:Entity {id:$sid,user_id:$uid}) "
                "MATCH (t:Entity {id:$tid,user_id:$uid}) "
                "MERGE (n)-[:MENTIONS]->(t) DELETE m",
                uid=user_id, sid=source_id, tid=target_id,
            )
            await tx.run(
                "MATCH (s:Entity {id:$sid,user_id:$uid})-[r:RELATED]->"
                "(o:Entity {user_id:$uid}) "
                "MATCH (t:Entity {id:$tid,user_id:$uid}) "
                "WHERE o.id <> $tid "
                "MERGE (t)-[:RELATED {user_id:$uid,source_kind:r.source_kind,"
                "source_id:r.source_id,relation_type:r.relation_type}]->(o) DELETE r",
                uid=user_id, sid=source_id, tid=target_id,
            )
            await tx.run(
                "MATCH (o:Entity {user_id:$uid})-[r:RELATED]->"
                "(s:Entity {id:$sid,user_id:$uid}) "
                "MATCH (t:Entity {id:$tid,user_id:$uid}) "
                "WHERE o.id <> $tid "
                "MERGE (o)-[:RELATED {user_id:$uid,source_kind:r.source_kind,"
                "source_id:r.source_id,relation_type:r.relation_type}]->(t) DELETE r",
                uid=user_id, sid=source_id, tid=target_id,
            )
            await tx.run(
                "MATCH (s:Entity {id:$sid,user_id:$uid})-[r:MANUAL_RELATION]->"
                "(o:Entity {user_id:$uid}) "
                "MATCH (t:Entity {id:$tid,user_id:$uid}) "
                "WHERE o.id <> $tid "
                "CREATE (t)-[nr:MANUAL_RELATION {id:randomUUID(),"
                "user_id:$uid,relation_type:r.relation_type}]->(o) DELETE r",
                uid=user_id, sid=source_id, tid=target_id,
            )
            await tx.run(
                "MATCH (o:Entity {user_id:$uid})-[r:MANUAL_RELATION]->"
                "(s:Entity {id:$sid,user_id:$uid}) "
                "MATCH (t:Entity {id:$tid,user_id:$uid}) "
                "WHERE o.id <> $tid "
                "CREATE (o)-[nr:MANUAL_RELATION {id:randomUUID(),"
                "user_id:$uid,relation_type:r.relation_type}]->(t) DELETE r",
                uid=user_id, sid=source_id, tid=target_id,
            )
            await tx.run(
                "MATCH (s:Entity {id:$sid,user_id:$uid}) DETACH DELETE s",
                uid=user_id, sid=source_id,
            )
            await tx.commit()
    rows = (await driver.execute_query(
        "MATCH (e:Entity {id:$id,user_id:$uid}) "
        "RETURN e.id AS id,e.name AS name,coalesce(e.display_name,e.name) AS display_name,"
        "e.entity_type AS type_id,e.description AS description,"
        "coalesce(e.aliases,[]) AS aliases",
        id=target_id, uid=user_id,
    )).records
    return {**one(rows), "confidence": 1.0, "source_note_ids": []}


async def list_types(user_id: str) -> list[dict]:
    from app.graph.maintenance import ensure_system_types
    await ensure_system_types(user_id)
    rows = (await graph_driver().execute_query(
        "MATCH (t:EntityType {user_id:$uid}) "
        "RETURN t.id AS id,t.user_id AS user_id,t.name AS name,"
        "t.display_name AS display_name,t.color AS color,t.icon AS icon,"
        "coalesce(t.is_system,false) AS is_system "
        "ORDER BY name", uid=user_id,
    )).records
    return [{
        **row.data(),
        "is_system": bool(row.data().get("is_system", False)),
    } for row in rows]


async def save_type(user_id: str, payload: TypeIn, type_id: str | None = None) -> dict:
    tid = type_id or str(uuid4())
    driver = graph_driver()
    if type_id is not None:
        owned = (await driver.execute_query(
            "MATCH (t:EntityType {id:$id,user_id:$uid}) RETURN t.id AS id",
            id=type_id, uid=user_id,
        )).records
        if not owned:
            raise HTTPException(status_code=404, detail="类型不存在")
    existing = (await driver.execute_query(
        "MATCH (t:EntityType {user_id:$uid,name:$name}) RETURN t.id AS id",
        uid=user_id, name=payload.name,
    )).records
    if existing and existing[0]["id"] != tid:
        raise HTTPException(status_code=409, detail="类型名称已存在")
    rows = (await driver.execute_query(
        "MERGE (t:EntityType {id:$id,user_id:$uid}) "
        "SET t.name=$name,t.display_name=$display,t.color=$color,t.icon=$icon "
        "RETURN t.id AS id,t.user_id AS user_id,t.name AS name,"
        "t.display_name AS display_name,t.color AS color,t.icon AS icon",
        id=tid, uid=user_id, name=payload.name,
        display=payload.display_name, color=payload.color, icon=payload.icon,
    )).records
    return {**one(rows), "is_system": False}


async def delete_type(user_id: str, type_id: str) -> None:
    rows = (await graph_driver().execute_query(
        "MATCH (t:EntityType {id:$id,user_id:$uid}) "
        "OPTIONAL MATCH (e:Entity {user_id:$uid,entity_type:$id}) "
        "SET e.entity_type=NULL "
        "WITH t,t.id AS found DELETE t RETURN found",
        id=type_id, uid=user_id,
    )).records
    one(rows)


async def create_relation(user_id: str, payload: RelationIn) -> dict:
    rid = str(uuid4())
    rows = (await graph_driver().execute_query(
        "MATCH (a:Entity {id:$aid,user_id:$uid}),"
        "(b:Entity {id:$bid,user_id:$uid}) "
        "CREATE (a)-[r:MANUAL_RELATION {id:$rid,user_id:$uid,"
        "relation_type:$rtype}]->(b) RETURN r.id AS id",
        aid=payload.source_id, bid=payload.target_id, uid=user_id,
        rid=rid, rtype=payload.relation_type,
    )).records
    one(rows, "关系端点不存在")
    return {"id": rid, "user_id": user_id, "source_id": payload.source_id,
            "target_id": payload.target_id, "relation_type": payload.relation_type,
            "properties": {}, "confidence": 1.0}


async def delete_relation(user_id: str, relation_id: str) -> None:
    rows = (await graph_driver().execute_query(
        "MATCH ()-[r:MANUAL_RELATION {id:$id,user_id:$uid}]->() "
        "WITH r,r.id AS found DELETE r RETURN found",
        id=relation_id, uid=user_id,
    )).records
    one(rows)
