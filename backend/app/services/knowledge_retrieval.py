"""MySQL 字面检索：当前用户笔记和知识切片。"""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_document import KnowledgeChunk, KnowledgeDocument
from app.models.note import Note
from app.schemas.models import RetrievalHit
from app.core.settings import settings
from app.services.retrieval_policy import normalize_query, short_snippet


class KnowledgeRetrieval:
    async def search(self, db: AsyncSession, user_id: str, query: str) -> list[RetrievalHit]:
        keyword = normalize_query(query)
        note_rows = await db.execute(
            select(Note).where(
                Note.user_id == user_id,
                or_(Note.title.contains(keyword, autoescape=True),
                    Note.content.contains(keyword, autoescape=True)),
            ).order_by(Note.updated_at.desc(), Note.id.desc()).limit(50)
        )
        chunk_rows = await db.execute(
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .where(
                KnowledgeDocument.user_id == user_id,
                KnowledgeChunk.content.contains(keyword, autoescape=True),
            ).order_by(KnowledgeDocument.created_at.desc(), KnowledgeChunk.index.asc()).limit(50)
        )
        hits: list[RetrievalHit] = []
        for note in note_rows.scalars().all():
            note_text = note.title + "\n" + note.content
            hits.append(RetrievalHit(
                source_kind="note", source_id=note.id, title=note.title,
                snippet=short_snippet(note_text, keyword),
                score=max(note_text.casefold().count(keyword.casefold()), 1),
            ))
        for chunk, doc in chunk_rows.all():
            hits.append(RetrievalHit(
                source_kind="knowledge_base", source_id=doc.id, title=doc.filename,
                snippet=short_snippet(chunk.content, keyword),
                chunk_id=chunk.id, chunk_index=chunk.index, page=chunk.page,
                parent_text=chunk.parent_text,
                score=max(chunk.content.casefold().count(keyword.casefold()), 1),
            ))
        hits.sort(key=lambda hit: (-hit.score, hit.source_kind, hit.source_id))
        return hits[:settings.RAG_RECALL_LIMIT]


knowledge_retrieval = KnowledgeRetrieval()
