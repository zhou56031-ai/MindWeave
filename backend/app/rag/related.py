"""关联卡片：候选召回后重新确认 MySQL 来源归属。"""

import math

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_document import KnowledgeDocument
from app.models.note import Note
from app.rag.embedding import embed
from app.rag.hybrid_retrieval import search


def cosine(a: list[float], b: list[float]) -> float:
    value = sum(x * y for x, y in zip(a, b))
    return max(0.0, min(1.0, value))


async def related_fragments(
    db: AsyncSession, user_id: str, note_id: str,
) -> list[dict]:
    note = await db.scalar(select(Note).where(
        Note.id == note_id,
        Note.user_id == user_id,
    ))
    if note is None:
        raise HTTPException(status_code=404, detail="笔记不存在")
    seed = (note.title + " " + note.content[:300]).strip()
    if not seed:
        return []
    hits = await search(db, user_id, seed[:100])
    seed_vector = await embed(seed[:500])
    result: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for hit in hits:
        key = (hit.source_kind, hit.source_id)
        if key in seen or key == ("note", note_id):
            continue
        seen.add(key)
        if hit.source_kind == "note":
            source = await db.scalar(select(Note).where(
                Note.id == hit.source_id,
                Note.user_id == user_id,
            ))
            if source is None:
                continue
            title, content, kind = source.title, source.content, "note"
        else:
            source = await db.scalar(select(KnowledgeDocument).where(
                KnowledgeDocument.id == hit.source_id,
                KnowledgeDocument.user_id == user_id,
            ))
            if source is None:
                continue
            title, content, kind = source.filename, hit.snippet, "knowledge_base"
        score = cosine(seed_vector, await embed(content[:500] or title))
        if not math.isfinite(score):
            continue
        result.append({
            "id": hit.source_id,
            "title": title,
            "content_preview": content[:180],
            "content": content[:1200],
            "similarity": round(score, 4),
            "source": kind,
        })
    return sorted(result, key=lambda item: -item["similarity"])[:5]
