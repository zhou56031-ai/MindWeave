"""在后台预热本地 Embedding，缩短首个检索请求。"""

import asyncio
import logging

from app.rag.embedding import embed

logger = logging.getLogger("mindweave.warmup")


async def warm_embedding() -> None:
    logger.info("embedding_warmup_started")
    try:
        await embed("预热")
    except Exception:
        logger.warning("embedding_warmup_failed", exc_info=True)
        return
    logger.info("embedding_warmup_completed")


def start_warmup() -> asyncio.Task:
    return asyncio.create_task(warm_embedding(), name="embedding-warmup")
