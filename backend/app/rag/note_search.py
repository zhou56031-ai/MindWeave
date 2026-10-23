"""语义笔记搜索：Neo4j 找候选，MySQL 回填并复核归属。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.note import Note
from app.rag.hybrid_retrieval import search
from app.services.retrieval_policy import normalize_query


async def semantic_note_search(
    db: AsyncSession,
    user_id: str,
    query: str,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Note], int]:
    keyword = normalize_query(query)
    hits = await search(db, user_id, keyword)
    note_ids: list[str] = []
    for hit in hits:
        if hit.source_kind == "note" and hit.source_id not in note_ids:
            note_ids.append(hit.source_id)
    if not note_ids:
        return [], 0

    rows = await db.execute(select(Note).where(
        Note.user_id == user_id,
        Note.id.in_(note_ids),
    ))
    notes_by_id = {note.id: note for note in rows.scalars().all()}
    ordered = [notes_by_id[note_id] for note_id in note_ids if note_id in notes_by_id]
    offset = (page - 1) * page_size
    return ordered[offset:offset + page_size], len(ordered)
