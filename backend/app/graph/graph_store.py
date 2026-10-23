"""按用户和来源替换图谱边；单次写入使用一个 Neo4j 事务。"""
from uuid import NAMESPACE_URL, uuid5

from app.graph.neo4j_client import graph_driver
from app.graph.schemas import ExtractResult


def entity_id(user_id: str, name: str) -> str:
    return str(uuid5(NAMESPACE_URL, user_id + ":" + name.strip().casefold()))


async def replace_source(
    user_id: str, kind: str, source_id: str, title: str, result: ExtractResult
) -> None:
    if kind not in {"note", "doc"}:
        raise ValueError("来源类型不支持")
    driver = graph_driver()
    async with driver.session() as session:
        async with await session.begin_transaction() as tx:
            await tx.run(
                "MERGE (s:Source {user_id:$uid,kind:$kind,id:$sid}) "
                "SET s.title=$title",
                uid=user_id, kind=kind, sid=source_id, title=title[:255],
            )
            await tx.run(
                "MATCH (s:Source {user_id:$uid,kind:$kind,id:$sid})-[r:MENTIONS]->() DELETE r",
                uid=user_id, kind=kind, sid=source_id,
            )
            await tx.run(
                "MATCH ()-[r:RELATED {user_id:$uid,source_kind:$kind,source_id:$sid}]->() DELETE r",
                uid=user_id, kind=kind, sid=source_id,
            )
            for item in result.entities:
                eid = entity_id(user_id, item.name)
                await tx.run(
                    "MERGE (e:Entity {id:$eid}) "
                    "SET e.user_id=$uid, e.name=$name, e.entity_type=$etype, "
                    "e.description=$description "
                    "WITH e MATCH (s:Source {user_id:$uid,kind:$kind,id:$sid}) "
                    "MERGE (s)-[:MENTIONS]->(e)",
                    eid=eid, uid=user_id, name=item.name.strip(),
                    etype=item.type, description=item.description,
                    kind=kind, sid=source_id,
                )
            for link in result.relations:
                await tx.run(
                    "MATCH (a:Entity {id:$source_eid,user_id:$uid}) "
                    "MATCH (b:Entity {id:$target_eid,user_id:$uid}) "
                    "MERGE (a)-[r:RELATED {user_id:$uid,source_kind:$kind,"
                    "source_id:$sid,relation_type:$rtype}]->(b)",
                    source_eid=entity_id(user_id, link.source),
                    target_eid=entity_id(user_id, link.target),
                    uid=user_id, kind=kind, sid=source_id,
                    rtype=link.relation_type,
                )
            await tx.commit()


async def delete_source(user_id: str, kind: str, source_id: str) -> None:
    if kind not in {"note", "doc"}:
        raise ValueError("来源类型不支持")
    driver = graph_driver()
    async with driver.session() as session:
        async with await session.begin_transaction() as tx:
            await tx.run(
                "MATCH ()-[r:RELATED {user_id:$uid,source_kind:$kind,source_id:$sid}]->() DELETE r",
                uid=user_id, kind=kind, sid=source_id,
            )
            await tx.run(
                "MATCH (s:Source {user_id:$uid,kind:$kind,id:$sid}) DETACH DELETE s",
                uid=user_id, kind=kind, sid=source_id,
            )
            await tx.commit()
