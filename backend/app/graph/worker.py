"""独立进程消费图构建任务：python -m app.graph.worker。"""
import asyncio
import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, select

from app.db.db_config import AsyncSessionLocal, async_engine, init_db
from app.graph.deep_links import link_chunk_entities, replace_wikilinks
from app.graph.extractor import extract_entities
from app.graph.graph_store import delete_source, entity_id, replace_source
from app.graph.maintenance import cleanup_orphan_entities, ensure_system_types
from app.graph.neo4j_client import close_graph_driver, ensure_graph_schema, graph_driver
from app.graph.task_recovery import recover_stale
from app.models.graph_extract_log import GraphExtractLog
from app.models.graph_task import GraphTask
from app.models.knowledge_document import KnowledgeChunk, KnowledgeDocument
from app.models.note import Note
from app.rag.chunk_index import delete_chunks, replace_chunks
from app.services.structured_chunks import CHUNK_VERSION, IndexPiece, section_from_text, split_structured


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _save_audit(
    *,
    user_id: str,
    kind: str,
    source_id: str,
    content_hash: str,
    status: str,
    new_count: int = 0,
    update_count: int = 0,
    error: str | None = None,
) -> None:
    async with AsyncSessionLocal() as db:
        log = await db.scalar(select(GraphExtractLog).where(
            GraphExtractLog.user_id == user_id,
            GraphExtractLog.source_kind == kind,
            GraphExtractLog.source_id == source_id,
        ))
        if log is None:
            log = GraphExtractLog(
                id=str(uuid4()),
                user_id=user_id,
                source_kind=kind,
                source_id=source_id,
                content_hash=content_hash,
                status=status,
            )
            db.add(log)
        log.content_hash = content_hash
        log.status = status
        log.new_count = new_count
        log.update_count = update_count
        log.error_message = error
        log.finished_at = _now() if status in {"success", "failed"} else None
        await db.commit()


async def process_one() -> bool:
    async with AsyncSessionLocal() as db:
        task = await db.scalar(
            select(GraphTask).where(GraphTask.status == "pending")
            .order_by(GraphTask.updated_at, GraphTask.id)
            .limit(1).with_for_update(skip_locked=True)
        )
        if task is None:
            return False
        task_id = task.id
        token = str(uuid4())
        task.status = "running"
        task.run_token = token
        task.attempts += 1
        user_id, kind, source_id = task.user_id, task.source_kind, task.source_id
        previous_hash = task.content_hash
        previous_index_version = task.index_version
        force = bool(task.force)
        await db.commit()

    body_hash = ""
    try:
        async with AsyncSessionLocal() as db:
            if kind == "note":
                source = await db.scalar(select(Note).where(
                    Note.id == source_id, Note.user_id == user_id))
                title = source.title if source else ""
                content = source.content if source else ""
            else:
                source = await db.scalar(select(KnowledgeDocument).where(
                    KnowledgeDocument.id == source_id,
                    KnowledgeDocument.user_id == user_id))
                title = source.filename if source else ""
                content = source.content if source else ""
            if source is None:
                pieces = []
            elif kind == "note":
                pieces = split_structured(content)
            else:
                rows = (await db.execute(select(KnowledgeChunk).where(
                    KnowledgeChunk.document_id == source_id,
                ).order_by(KnowledgeChunk.index))).scalars().all()
                pieces = [IndexPiece(row.content, row.page, section_from_text(row.content)) for row in rows]
        if source is None:
            await delete_source(user_id, kind, source_id)
            await delete_chunks(user_id, kind, source_id)
            async with AsyncSessionLocal() as db:
                await db.execute(delete(GraphExtractLog).where(
                    GraphExtractLog.user_id == user_id,
                    GraphExtractLog.source_kind == kind,
                    GraphExtractLog.source_id == source_id,
                ))
                await db.commit()
        else:
            body_hash = hashlib.md5(content.encode()).hexdigest()
            async with AsyncSessionLocal() as db:
                previous_log = await db.scalar(select(GraphExtractLog).where(
                    GraphExtractLog.user_id == user_id,
                    GraphExtractLog.source_kind == kind,
                    GraphExtractLog.source_id == source_id,
                    GraphExtractLog.status == "success",
                    GraphExtractLog.content_hash == body_hash,
                ))
            if (not force and previous_hash == body_hash and previous_log is not None
                    and previous_index_version == CHUNK_VERSION):
                async with AsyncSessionLocal() as db:
                    current = await db.scalar(select(GraphTask).where(
                        GraphTask.id == task_id,
                    ).with_for_update())
                    if current and current.run_token == token:
                        current.status = "completed"
                        current.run_token = None
                        current.error_message = None
                        await db.commit()
                return True

            await _save_audit(
                user_id=user_id,
                kind=kind,
                source_id=source_id,
                content_hash=body_hash,
                status="pending",
            )
            old_rows = (await graph_driver().execute_query(
                "MATCH (:Source {user_id:$uid,kind:$kind,id:$sid})"
                "-[:MENTIONS]->(e:Entity) RETURN collect(e.id) AS ids",
                uid=user_id, kind=kind, sid=source_id,
            )).records
            old_ids = old_rows[0]["ids"] if old_rows else []
            await ensure_system_types(user_id)
            result = await extract_entities(content)
            async with AsyncSessionLocal() as db:
                current = await db.scalar(select(GraphTask).where(GraphTask.id == task_id))
                if current is None or current.run_token != token:
                    return True
            await replace_source(user_id, kind, source_id, title, result)
            async def index_progress(done: int, total: int):
                async with AsyncSessionLocal() as db:
                    current = await db.scalar(select(GraphTask).where(
                        GraphTask.id == task_id,
                    ).with_for_update())
                    if current is None or current.run_token != token:
                        raise RuntimeError("索引任务已被更新，本轮停止发布")
                    current.index_done = done
                    current.index_total = total
                    await db.commit()

            await replace_chunks(user_id, kind, source_id, title, content,
                                 pieces=pieces, progress=index_progress)
            new_ids = {entity_id(user_id, item.name) for item in result.entities}
            await cleanup_orphan_entities(
                user_id, [value for value in old_ids if value not in new_ids],
            )
            await _save_audit(
                user_id=user_id,
                kind=kind,
                source_id=source_id,
                content_hash=body_hash,
                status="success",
                new_count=len(result.entities),
                update_count=len(result.relations),
            )
            async with AsyncSessionLocal() as db:
                current = await db.scalar(select(GraphTask).where(
                    GraphTask.id == task_id,
                ).with_for_update())
                if current and current.run_token == token:
                    current.title = title
                    current.content_hash = body_hash
                    current.index_version = CHUNK_VERSION
                    current.force = 0
                    await db.commit()
            await link_chunk_entities(
                user_id, kind, source_id, [piece.text for piece in pieces],
            )
            if kind == "note":
                async with AsyncSessionLocal() as db:
                    await replace_wikilinks(
                        db, user_id, source_id, title, content,
                    )
        error = None
    except Exception as exc:
        error = str(exc)[:500]
        if body_hash:
            try:
                await _save_audit(
                    user_id=user_id,
                    kind=kind,
                    source_id=source_id,
                    content_hash=body_hash,
                    status="failed",
                    error=error,
                )
            except Exception:
                pass

    async with AsyncSessionLocal() as db:
        current = await db.scalar(select(GraphTask).where(GraphTask.id == task_id).with_for_update())
        if current is None or current.run_token != token:
            return True
        current.status = ("pending" if current.attempts < 3 else "failed") if error else "completed"
        current.error_message = error
        current.run_token = None
        await db.commit()
    return True


async def main() -> None:
    await init_db()
    await ensure_graph_schema()
    await recover_stale()
    try:
        while True:
            if not await process_one():
                await recover_stale()
                await asyncio.sleep(2)
    finally:
        await close_graph_driver()
        await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
