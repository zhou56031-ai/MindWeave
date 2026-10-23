import asyncio
from contextlib import suppress
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.core.warmup import start_warmup
from app.db.db_config import async_engine, init_db
from app.db.redis_config import close_redis
from app.graph.neo4j_client import close_graph_driver


@asynccontextmanager
async def lifespan(app: FastAPI):
    warmup_task: asyncio.Task | None = None
    try:
        # 【新增】启动时先验证本项目账户可以连接目标数据库。
        async with async_engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        # 【新增 C01】开始接收请求前，保证本阶段的表已经存在。
        await init_db()
        warmup_task = start_warmup()
        yield
    finally:
        if warmup_task is not None and not warmup_task.done():
            warmup_task.cancel()
            with suppress(asyncio.CancelledError):
                await warmup_task
        # 【新增】启动失败或应用正常关闭时，都释放连接池资源。
        await close_graph_driver()
        await close_redis()
        await async_engine.dispose()
