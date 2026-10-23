"""把 ~/autorag-lab/ocr/text 下的股票课程 OCR 文本导入用户 123 的知识库。"""
import asyncio
import hashlib
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db.db_config import AsyncSessionLocal, async_engine
from app.models.knowledge_document import KnowledgeChunk, KnowledgeDocument
from app.models.user_model import User
from app.rag.chunk_index import replace_chunks
from app.services.structured_chunks import parent_map, split_structured

OCR = Path.home() / "autorag-lab" / "ocr" / "text"
USER = "e00b36a96f7f492d923ddfd0"  # 123


async def main() -> None:
    paths = sorted(OCR.glob("*.txt"))
    print("待导入:", len(paths), flush=True)
    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(User.uuid == USER))
        assert user is not None, "用户 123 不存在"
        existing = set((await db.scalars(select(KnowledgeDocument.filename).where(
            KnowledgeDocument.user_id == USER))).all())

        for number, path in enumerate(paths, 1):
            content = path.read_text(encoding="utf-8").strip()
            if len(content) < 200:
                continue
            filename = f"股票课程/{path.stem}.md"
            if filename in existing:
                print(f"[{number}/{len(paths)}] 跳过已存在 {filename}", flush=True)
                continue
            pieces = split_structured(content)
            parents = parent_map(pieces)
            document = KnowledgeDocument(
                id=str(uuid4()), user_id=USER, filename=filename,
                md5=hashlib.md5(content.encode()).hexdigest(),
                file_size=len(content.encode()), content=content,
                status="completed", chunk_count=len(pieces),
            )
            db.add(document)
            await db.flush()
            db.add_all([
                KnowledgeChunk(
                    id=str(uuid4()), document_id=document.id, index=index,
                    content=piece.text, page=piece.page, images=[],
                    parent_id=parents[index][0], parent_text=parents[index][1],
                )
                for index, piece in enumerate(pieces)
            ])
            await db.commit()
            await replace_chunks(USER, "doc", document.id, filename, content, pieces=pieces)
            print(f"[{number}/{len(paths)}] {filename} -> {len(pieces)} 片", flush=True)

    await async_engine.dispose()
    print("导入完成", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
