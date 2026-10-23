"""知识文档的用户范围查询与导入服务。"""

from hashlib import md5
from uuid import uuid4

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.failed_response import BusinessException
from app.graph.task_queue import enqueue_graph
from app.models.knowledge_document import KnowledgeChunk, KnowledgeDocument
from app.schemas.models import (
    DocumentChunksResponse, KnowledgeChunkResponse, KnowledgeDocumentDetail,
    KnowledgeDocumentResponse, KnowledgeListResponse, MD5ListResponse, MD5Record,
)
from app.services.document_extract import extract_pages
from app.services.structured_chunks import parent_map, split_structured
from app.services.pdf_vision import enrich_pdf, remove_images


class KnowledgeService:
    async def _find_document(
        self, db: AsyncSession, user_id: str, filename: str
    ) -> KnowledgeDocument | None:
        return await db.scalar(select(KnowledgeDocument).where(
            KnowledgeDocument.user_id == user_id,
            KnowledgeDocument.filename == filename,
        ))

    async def _chunks(
        self, db: AsyncSession, document_id: str
    ) -> list[KnowledgeChunkResponse]:
        result = await db.execute(
            select(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id)
            .order_by(KnowledgeChunk.index.asc())
        )
        return [KnowledgeChunkResponse(
            chunk_id=chunk.id, index=chunk.index, content=chunk.content,
            page=chunk.page, images=chunk.images or [],
        ) for chunk in result.scalars().all()]

    async def get_detail(
        self, db: AsyncSession, user_id: str, filename: str
    ) -> KnowledgeDocumentDetail | None:
        document = await self._find_document(db, user_id, filename)
        if document is None:
            return None
        chunks = await self._chunks(db, document.id)
        return KnowledgeDocumentDetail(
            id=document.id, filename=document.filename, user_id=document.user_id,
            md5=document.md5, chunk_count=len(chunks), content=document.content, chunks=chunks,
            created_at=document.created_at,
        )

    async def get_chunks(
        self, db: AsyncSession, user_id: str, filename: str
    ) -> DocumentChunksResponse | None:
        document = await self._find_document(db, user_id, filename)
        if document is None:
            return None
        chunks = await self._chunks(db, document.id)
        return DocumentChunksResponse(
            filename=document.filename, total_chunks=len(chunks), chunks=chunks
        )

    async def delete_document(
        self, db: AsyncSession, user_id: str, filename: str
    ) -> bool:
        document = await self._find_document(db, user_id, filename)
        if document is None:
            return False
        # 【新增】先删子切片，再删父文档；只提交一次。
        await db.execute(delete(KnowledgeChunk).where(
            KnowledgeChunk.document_id == document.id
        ))
        await db.delete(document)
        await enqueue_graph(db, user_id, "doc", document.id)
        await db.commit()
        remove_images(user_id, document.md5)
        return True

    async def delete_by_md5(
        self, db: AsyncSession, user_id: str, md5_value: str
    ) -> bool:
        document = await db.scalar(select(KnowledgeDocument).where(
            KnowledgeDocument.user_id == user_id,
            KnowledgeDocument.md5 == md5_value,
        ))
        return False if document is None else await self.delete_document(
            db, user_id, document.filename
        )

    async def clean_all(self, db: AsyncSession, user_id: str) -> int:
        result = await db.execute(select(
            KnowledgeDocument.id, KnowledgeDocument.md5
        ).where(KnowledgeDocument.user_id == user_id))
        documents = list(result.all())
        ids = [document_id for document_id, _ in documents]
        if not ids:
            return 0
        await db.execute(delete(KnowledgeChunk).where(
            KnowledgeChunk.document_id.in_(ids)
        ))
        await db.execute(delete(KnowledgeDocument).where(
            KnowledgeDocument.user_id == user_id
        ))
        for document_id in ids:
            await enqueue_graph(db, user_id, "doc", document_id)
        await db.commit()
        for _, md5_value in documents:
            remove_images(user_id, md5_value)
        return len(ids)

    async def list_md5(self, db: AsyncSession, user_id: str) -> MD5ListResponse:
        result = await db.execute(select(KnowledgeDocument).where(
            KnowledgeDocument.user_id == user_id
        ).order_by(KnowledgeDocument.created_at.desc()))
        records = [MD5Record(
            md5=document.md5, filename=document.filename,
            original_filename=document.filename,
            upload_time=document.created_at.isoformat(),
        ) for document in result.scalars().all()]
        return MD5ListResponse(records=records, total_count=len(records))

    async def get_md5(
        self, db: AsyncSession, user_id: str, md5_value: str,
    ) -> MD5Record | None:
        row = await db.scalar(select(KnowledgeDocument).where(
            KnowledgeDocument.user_id == user_id,
            KnowledgeDocument.md5 == md5_value,
        ))
        if row is None:
            return None
        return MD5Record(
            md5=row.md5,
            filename=row.filename,
            original_filename=row.filename,
            upload_time=row.created_at.isoformat(),
        )

    async def clear_md5(
        self, db: AsyncSession, user_id: str, delete_documents: bool,
    ) -> int:
        if not delete_documents:
            raise BusinessException(
                code=4002,
                message="当前 MySQL 权威文档模型不支持保留正文单独清空 MD5",
            )
        return await self.clean_all(db, user_id)

    async def add_document(
        self, db: AsyncSession, user_id: str, filename: str, raw: bytes
    ) -> KnowledgeDocumentResponse:
        safe_name, pages = extract_pages(filename, raw)
        digest = md5(raw).hexdigest()
        existing = await db.scalar(
            select(KnowledgeDocument.id).where(
                KnowledgeDocument.user_id == user_id,
                or_(KnowledgeDocument.filename == safe_name, KnowledgeDocument.md5 == digest),
            )
        )
        if existing is not None:
            raise BusinessException(code=4002, message="文件名或文件内容已导入")
        page_images: dict[int, list[str]] = {}
        if safe_name.lower().endswith(".pdf"):
            try:
                pages, page_images = await enrich_pdf(raw, user_id, digest, pages)
            except Exception:
                remove_images(user_id, digest)
                raise
        content = "\n\n".join(text for _, text in pages)
        pieces = [piece for page, text in pages for piece in split_structured(text, page)]
        parents = parent_map(pieces)
        document = KnowledgeDocument(
            id=str(uuid4()), user_id=user_id, filename=safe_name,
            md5=digest, file_size=len(raw), content=content,
            status="completed", chunk_count=len(pieces),
        )
        try:
            db.add(document)
            # 【新增】先在当前事务写入父记录，让切片外键有目标；尚未提交。
            await db.flush()
            db.add_all([
                KnowledgeChunk(
                    id=str(uuid4()), document_id=document.id, index=index,
                    content=piece.text, page=piece.page,
                    images=page_images.get(piece.page, []),
                    parent_id=parents[index][0] if index < len(parents) else None,
                    parent_text=parents[index][1] if index < len(parents) else None,
                )
                for index, piece in enumerate(pieces)
            ])
            await enqueue_graph(db, user_id, "doc", document.id)
            # 【新增】文档和全部切片一次提交；唯一约束挡住并发重复导入。
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            # 并发导入同一 PDF 时，失败的一方不能删掉已提交一方的图片。
            owned = await db.scalar(select(KnowledgeDocument.id).where(
                KnowledgeDocument.user_id == user_id,
                KnowledgeDocument.md5 == digest,
            ))
            if owned is None:
                remove_images(user_id, digest)
            if exc.orig.args and exc.orig.args[0] == 1062:
                raise BusinessException(code=4002, message="文件名或文件内容已导入") from exc
            raise
        except Exception:
            await db.rollback()
            remove_images(user_id, digest)
            raise
        await db.refresh(document)
        return KnowledgeDocumentResponse.model_validate(document).model_copy(
            update={"file_type": safe_name.rsplit(".", 1)[-1].lower(), "preview": content[:120]}
        )

    async def list_documents(
        self, db: AsyncSession, user_id: str
    ) -> KnowledgeListResponse:
        result = await db.execute(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.user_id == user_id)
            .order_by(KnowledgeDocument.created_at.desc(), KnowledgeDocument.id.desc())
        )
        documents = [
            KnowledgeDocumentResponse.model_validate(document).model_copy(
                update={
                    "file_type": document.filename.rsplit(".", 1)[-1].lower(),
                    "preview": document.content[:120],
                }
            )
            for document in result.scalars().all()
        ]
        return KnowledgeListResponse(documents=documents, total_count=len(documents))


knowledge_service = KnowledgeService()
