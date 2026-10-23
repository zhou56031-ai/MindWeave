"""按用户名为已有资料重排图任务；只登记，不直接调用模型。"""
import argparse
import asyncio
from sqlalchemy import select
from app.db.db_config import AsyncSessionLocal, async_engine
from app.graph.task_queue import enqueue_graph
from app.models.knowledge_document import KnowledgeDocument
from app.models.note import Note
from app.models.user_model import User


async def main(username: str):
    try:
        async with AsyncSessionLocal() as db:
            user = await db.scalar(select(User).where(User.username == username))
            if user is None:
                raise ValueError("用户名不存在")
            user_id = user.uuid
        for kind, model in (("note", Note), ("doc", KnowledgeDocument)):
            cursor = ""
            while True:
                async with AsyncSessionLocal() as db:
                    ids = list((await db.scalars(select(model.id).where(
                        model.user_id == user_id, model.id > cursor,
                    ).order_by(model.id).limit(50))).all())
                    if not ids:
                        break
                    for source_id in ids:
                        await enqueue_graph(db, user_id, kind, source_id, force=True)
                    await db.commit()
                    cursor = ids[-1]
                print(f"已登记 {kind} 来源：{len(ids)} 个")
    finally:
        await async_engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    arguments = parser.parse_args()
    asyncio.run(main(arguments.username))
