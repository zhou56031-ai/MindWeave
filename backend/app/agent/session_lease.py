"""会话级短租约；聊天与审批恢复必须使用同一个键。"""
import hashlib
from contextlib import asynccontextmanager
from uuid import uuid4
from fastapi import HTTPException
from app.db.redis_config import get_redis

RELEASE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


@asynccontextmanager
async def session_lease(user_id: str, session_id: str):
    digest = hashlib.sha256(f"{user_id}:{session_id}".encode()).hexdigest()
    key, token = f"rag:chat:lease:{digest}", str(uuid4())
    redis = get_redis()
    acquired = False
    try:
        acquired = bool(await redis.set(key, token, nx=True, ex=240))
        if not acquired:
            raise HTTPException(409, "本会话正在处理上一条请求")
        yield
    finally:
        if acquired:
            try:
                await redis.eval(RELEASE, 1, key, token)
            except Exception:
                pass  # TTL 最终回收；不能用无条件 DEL 删除新租约。
        await redis.aclose()
