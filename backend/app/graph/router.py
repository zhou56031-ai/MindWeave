"""前端图谱画布的只读与人工编辑 HTTP 接口。"""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.success_response import success_response
from app.db.db_config import AsyncSessionLocal, get_db
from app.graph import edit_service as edits
from app.graph.edit_schemas import EntityIn, MergeIn, RelationIn, TypeIn
from app.graph.neo4j_client import graph_driver
from app.graph.task_queue import enqueue_graph
from app.graph.views import entity_detail, entity_sources, graph_view
from app.models.graph_extract_log import GraphExtractLog
from app.models.graph_task import GraphTask
from app.models.note import Note
from app.utils.auth_utils import get_current_user_id

graph_router = APIRouter(prefix="/api/graph", tags=["graph"])


@graph_router.get("/overview")
async def overview(
    types: str | None = Query(default=None, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    user_id: str = Depends(get_current_user_id),
):
    entity_types = [
        value.strip() for value in (types or "").split(",") if value.strip()
    ] or None
    return success_response(data=await graph_view(
        user_id, entity_types=entity_types, limit=limit,
    ))


@graph_router.get("/entity/{entity_id}")
async def entity(entity_id: str, user_id: str = Depends(get_current_user_id)):
    return success_response(data=await entity_detail(user_id, entity_id))


@graph_router.get("/entity/{entity_id}/neighbors")
async def neighbors(
    entity_id: str, depth: int = Query(1, ge=1, le=3),
    user_id: str = Depends(get_current_user_id),
):
    if await entity_detail(user_id, entity_id) is None:
        raise HTTPException(status_code=404, detail="实体不存在")
    rows = (await graph_driver().execute_query(
        f"MATCH p=(e:Entity {{user_id:$uid,id:$eid}})"
        f"-[:RELATED|MANUAL_RELATION*1..{depth}]-(other:Entity) "
        "WHERE all(n IN nodes(p) WHERE n.user_id=$uid) "
        "RETURN DISTINCT other.id AS id LIMIT 50",
        uid=user_id, eid=entity_id,
    )).records
    ids = [entity_id] + [record["id"] for record in rows]
    view = await graph_view(user_id, limit=200)
    view["nodes"] = [
        node for node in view["nodes"]
        if node["node_type"] != "entity" or node["id"] in ids
    ]
    allowed = {node["id"] for node in view["nodes"]}
    view["edges"] = [
        edge for edge in view["edges"]
        if edge["source"] in allowed and edge["target"] in allowed
    ]
    return success_response(data=view)


@graph_router.get("/entity/{entity_id}/notes")
async def sources(entity_id: str, user_id: str = Depends(get_current_user_id)):
    return success_response(data=await entity_sources(user_id, entity_id))


@graph_router.get("/notes/{note_id}/related")
async def note_related(note_id: str, user_id: str = Depends(get_current_user_id)):
    return success_response(data=await graph_view(
        user_id, source_kind="note", source_id=note_id, limit=200,
    ))


@graph_router.post("/notes/{note_id}/re-extract")
async def reextract_note(
    note_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    owned = await db.scalar(select(Note.id).where(
        Note.id == note_id,
        Note.user_id == user_id,
    ))
    if owned is None:
        raise HTTPException(status_code=404, detail="笔记不存在")
    await enqueue_graph(db, user_id, "note", note_id, force=True)
    await db.commit()
    return success_response(data={"triggered": True})


@graph_router.get("/docs/{doc_id}/related")
async def doc_related(doc_id: str, user_id: str = Depends(get_current_user_id)):
    return success_response(data=await graph_view(
        user_id, source_kind="doc", source_id=doc_id, limit=200,
    ))


@graph_router.get("/search")
async def search(
    q: str = Query(min_length=1, max_length=100),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    rows = (await graph_driver().execute_query(
        "MATCH (e:Entity {user_id:$uid}) WHERE toLower(e.name) CONTAINS toLower($q) "
        "RETURN e.id AS id,e.name AS name,e.entity_type AS type_id LIMIT 10",
        uid=user_id, q=q,
    )).records
    notes = (await db.execute(select(Note).where(
        Note.user_id == user_id, Note.title.contains(q, autoescape=True)
    ).limit(10))).scalars().all()
    return success_response(data={
        "entities": [dict(row) for row in rows],
        "notes": [{"id": note.id, "title": note.title} for note in notes],
    })


@graph_router.get("/extract-logs")
async def extract_logs(
    note_id: str | None = None,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(GraphTask).where(GraphTask.user_id == user_id)
    if note_id:
        stmt = stmt.where(GraphTask.source_id == note_id)
    tasks = (await db.execute(
        stmt.order_by(GraphTask.updated_at.desc()).limit(50)
    )).scalars().all()
    log_stmt = select(GraphExtractLog).where(
        GraphExtractLog.user_id == user_id,
    )
    if note_id:
        log_stmt = log_stmt.where(GraphExtractLog.source_id == note_id)
    log_rows = (await db.execute(log_stmt)).scalars().all()
    logs = {
        (row.source_kind, row.source_id): row
        for row in log_rows
    }
    return success_response(data=[{
        "note_id": task.source_id,
        "index_total": task.index_total,
        "index_done": task.index_done,
        "index_version": task.index_version,
        "source_type": task.source_kind,
        "content_hash": (
            logs[(task.source_kind, task.source_id)].content_hash
            if (task.source_kind, task.source_id) in logs
            else task.content_hash
        ),
        "status": (
            logs[(task.source_kind, task.source_id)].status
            if (task.source_kind, task.source_id) in logs
            else ("success" if task.status == "completed" else task.status)
        ),
        "new_count": (
            logs[(task.source_kind, task.source_id)].new_count
            if (task.source_kind, task.source_id) in logs
            else 0
        ),
        "update_count": (
            logs[(task.source_kind, task.source_id)].update_count
            if (task.source_kind, task.source_id) in logs
            else 0
        ),
        "error_message": (
            logs[(task.source_kind, task.source_id)].error_message
            if (task.source_kind, task.source_id) in logs
            else task.error_message
        ),
    } for task in tasks])


@graph_router.get("/events")
async def events(user_id: str = Depends(get_current_user_id)):
    async def stream():
        previous = {}
        while True:
            async with AsyncSessionLocal() as db:
                rows = (await db.execute(select(GraphTask).where(
                    GraphTask.user_id == user_id
                ).order_by(GraphTask.updated_at.desc()).limit(50))).scalars().all()
                for task in rows:
                    marker = (task.status, task.updated_at)
                    if previous.get(task.id) == marker:
                        continue
                    previous[task.id] = marker
                    kind = "extract_done" if task.status == "completed" else (
                        "extract_failed" if task.status == "failed" else "ping"
                    )
                    payload = {
                        "type": kind, "note_id": task.source_id,
                        "source_type": task.source_kind, "status": task.status,
                    }
                    yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(stream(), media_type="text/event-stream")


@graph_router.post("/entities")
async def create_entity(payload: EntityIn, user_id: str = Depends(get_current_user_id)):
    return success_response(data=await edits.create_entity(user_id, payload))


@graph_router.put("/entities/{entity_id}")
async def update_entity(
    entity_id: str, payload: EntityIn,
    user_id: str = Depends(get_current_user_id),
):
    return success_response(data=await edits.update_entity(user_id, entity_id, payload))


@graph_router.delete("/entities/{entity_id}")
async def delete_entity(entity_id: str, user_id: str = Depends(get_current_user_id)):
    await edits.delete_entity(user_id, entity_id)
    return success_response(message="实体已删除")


@graph_router.post("/entities/merge")
async def merge_entity(payload: MergeIn, user_id: str = Depends(get_current_user_id)):
    return success_response(data=await edits.merge_entities(
        user_id, payload.target_id, payload.source_id,
    ))


@graph_router.get("/types")
async def types(user_id: str = Depends(get_current_user_id)):
    return success_response(data=await edits.list_types(user_id))


@graph_router.post("/types")
async def create_type(payload: TypeIn, user_id: str = Depends(get_current_user_id)):
    return success_response(data=await edits.save_type(user_id, payload))


@graph_router.put("/types/{type_id}")
async def update_type(
    type_id: str, payload: TypeIn,
    user_id: str = Depends(get_current_user_id),
):
    return success_response(data=await edits.save_type(user_id, payload, type_id))


@graph_router.delete("/types/{type_id}")
async def remove_type(type_id: str, user_id: str = Depends(get_current_user_id)):
    await edits.delete_type(user_id, type_id)
    return success_response(message="类型已删除")


@graph_router.post("/relations")
async def create_relation(
    payload: RelationIn, user_id: str = Depends(get_current_user_id),
):
    return success_response(data=await edits.create_relation(user_id, payload))


@graph_router.delete("/relations/{relation_id}")
async def delete_relation(
    relation_id: str, user_id: str = Depends(get_current_user_id),
):
    await edits.delete_relation(user_id, relation_id)
    return success_response(message="关系已删除")
