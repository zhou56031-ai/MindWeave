"""分批暂存全部切片；成功后在 Neo4j 事务中切换可检索标签。"""
from uuid import uuid4
from app.core.agent_trace import emit
from app.core.settings import settings
from app.graph.neo4j_client import graph_driver
from app.rag.embedding import embed_many
from app.services.structured_chunks import CHUNK_VERSION, parent_map, split_structured


async def replace_chunks(
    user_id: str, kind: str, source_id: str, title: str, content: str,
    *, pieces=None, progress=None,
) -> None:
    parts = list(pieces) if pieces is not None else split_structured(content)
    parents = parent_map(parts)
    generation = str(uuid4())
    driver = graph_driver()
    total = len(parts)

    async def report(done):
        if progress is not None:
            await progress(done, total)

    await report(0)
    try:
        for start in range(0, total, settings.RAG_INDEX_BATCH_SIZE):
            batch = parts[start:start + settings.RAG_INDEX_BATCH_SIZE]
            vectors = await embed_many([piece.text for piece in batch])
            rows = [{
                "id": f"{generation}:{start + offset}", "user_id": user_id,
                "kind": kind, "source_id": source_id, "source_name": title[:255],
                "chunk_index": start + offset, "text": piece.text,
                "page": piece.page, "section": piece.section,
                "parent_id": parents[start + offset][0] if start + offset < len(parents) else None,
                "parent_text": parents[start + offset][1] if start + offset < len(parents) else None,
                "generation": generation, "chunk_version": CHUNK_VERSION,
                "embedding": vector,
            } for offset, (piece, vector) in enumerate(zip(batch, vectors))]
            await driver.execute_query(
                "UNWIND $rows AS row CREATE (c:ChunkStaging) SET c = row",
                rows=rows,
            )
            await report(start + len(batch))
        # 在激活前再确认本轮任务令牌；不能在很早以前只检查一次。
        await report(total)
        async with driver.session() as session:
            async with await session.begin_transaction() as tx:
                await tx.run(
                    "MATCH (c:Chunk {user_id:$uid,kind:$kind,source_id:$sid}) DETACH DELETE c",
                    uid=user_id, kind=kind, sid=source_id,
                )
                await tx.run(
                    "MATCH (c:ChunkStaging {user_id:$uid,generation:$generation}) "
                    "SET c:Chunk REMOVE c:ChunkStaging",
                    uid=user_id, generation=generation,
                )
                await tx.commit()
    finally:
        # 正常发布后已没有暂存标签；失败或取消只删除本代未发布节点。
        try:
            await driver.execute_query(
                "MATCH (c:ChunkStaging {user_id:$uid,generation:$generation}) DETACH DELETE c",
                uid=user_id, generation=generation,
            )
        except Exception as exc:
            emit("rag.index.cleanup_failed", generation=generation, error_type=type(exc).__name__)


async def delete_chunks(user_id: str, kind: str, source_id: str) -> None:
    await graph_driver().execute_query(
        "MATCH (c) WHERE (c:Chunk OR c:ChunkStaging) AND c.user_id=$uid "
        "AND c.kind=$kind AND c.source_id=$sid DETACH DELETE c",
        uid=user_id, kind=kind, sid=source_id,
    )
