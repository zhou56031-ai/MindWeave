"""Chunk 实体提及与笔记 WIKI 边。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.graph.link_parser import parse_links
from app.graph.neo4j_client import graph_driver
from app.models.note import Note


async def link_chunk_entities(
    user_id: str,
    kind: str,
    source_id: str,
    texts: list[str],
) -> None:
    rows = (await graph_driver().execute_query(
        "MATCH (e:Entity {user_id:$uid}) "
        "RETURN e.id AS id,e.name AS name",
        uid=user_id,
    )).records
    entities = [
        (row["id"], row["name"].casefold())
        for row in rows
        if row["name"]
    ]
    for index, text in enumerate(texts):
        folded = text.casefold()
        for entity_id, name in entities:
            if name in folded:
                await graph_driver().execute_query(
                    "MATCH (c:Chunk {user_id:$uid,kind:$kind,"
                    "source_id:$sid,chunk_index:$index}) "
                    "MATCH (e:Entity {user_id:$uid,id:$eid}) "
                    "MERGE (c)-[:MENTIONS]->(e)",
                    uid=user_id,
                    kind=kind,
                    sid=source_id,
                    index=index,
                    eid=entity_id,
                )


async def replace_wikilinks(
    db: AsyncSession,
    user_id: str,
    note_id: str,
    title: str,
    content: str,
) -> None:
    titles = parse_links(content)
    targets = []
    if titles:
        rows = await db.execute(select(Note).where(
            Note.user_id == user_id,
            Note.title.in_(titles),
            Note.id != note_id,
        ))
        targets = [
            {"id": note.id, "title": note.title}
            for note in rows.scalars().all()
        ]

    driver = graph_driver()
    await driver.execute_query(
        "MERGE (n:Note {user_id:$uid,id:$nid}) SET n.title=$title",
        uid=user_id,
        nid=note_id,
        title=title,
    )
    await driver.execute_query(
        "MATCH (:Note {user_id:$uid,id:$nid})-"
        "[r:WIKI {user_id:$uid}]->() DELETE r",
        uid=user_id,
        nid=note_id,
    )
    for target in targets:
        await driver.execute_query(
            "MERGE (a:Note {user_id:$uid,id:$aid}) "
            "MERGE (b:Note {user_id:$uid,id:$bid}) "
            "SET b.title=$title "
            "MERGE (a)-[:WIKI {user_id:$uid,kind:'wiki'}]->(b)",
            uid=user_id,
            aid=note_id,
            bid=target["id"],
            title=target["title"],
        )
