"""把 demo-docs / docs 下的 Markdown 灌入 eval-bot 的知识库（可重复执行）。"""
import asyncio
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.common import CORPUS_FILES, EVAL_USER  # noqa: E402

from sqlalchemy import delete, select  # noqa: E402

from app.db.db_config import AsyncSessionLocal, async_engine  # noqa: E402
from app.models.knowledge_document import KnowledgeChunk, KnowledgeDocument
from app.models.user_model import User
from app.rag.chunk_index import delete_chunks, replace_chunks
from app.services.structured_chunks import parent_map, split_structured
from app.services.user_service import hash_password

PASSWORD = "eval-bot-password"


async def main() -> None:
    files = [path for path in CORPUS_FILES if path.exists()]
    print("待导入文档:", len(files))

    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == EVAL_USER))
        if user is None:
            user = User(username=EVAL_USER, email="eval-bot@example.com",
                        password=hash_password(PASSWORD))
            db.add(user)
            await db.commit()
            await db.refresh(user)
        uid = user.uuid

        old = (await db.scalars(select(KnowledgeDocument).where(
            KnowledgeDocument.user_id == uid))).all()
        for document in old:
            await delete_chunks(uid, "doc", document.id)
            await db.execute(delete(KnowledgeChunk).where(
                KnowledgeChunk.document_id == document.id))
            await db.delete(document)
        await db.commit()

        total = 0
        for path in files:
            content = path.read_text(encoding="utf-8")
            if not content.strip():
                continue
            pieces = split_structured(content)
            parents = parent_map(pieces)
            document = KnowledgeDocument(
                id=hashlib.md5(f"{uid}:{path}".encode()).hexdigest()[:32],
                user_id=uid, filename=str(path.relative_to(path.parents[1])),
                md5=hashlib.md5(content.encode()).hexdigest(),
                file_size=len(content.encode()), content=content,
                status="completed", chunk_count=len(pieces),
            )
            db.add(document)
            await db.flush()
            db.add_all([
                KnowledgeChunk(
                    id=hashlib.md5(f"{document.id}:{index}".encode()).hexdigest()[:32],
                    document_id=document.id, index=index, content=piece.text,
                    page=piece.page, images=[],
                    parent_id=parents[index][0], parent_text=parents[index][1],
                )
                for index, piece in enumerate(pieces)
            ])
            await db.commit()
            await replace_chunks(uid, "doc", document.id, document.filename,
                                 content, pieces=pieces)
            total += len(pieces)

        print(f"导入完成：{len(files)} 篇，{total} 个切片，用户 {EVAL_USER}")
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
