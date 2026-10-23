from redis.asyncio import ConnectionPool, Redis

from app.core.settings import settings

pool = ConnectionPool(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    db=settings.REDIS_DB,
    decode_responses=True,
)


def get_redis() -> Redis:
    return Redis(connection_pool=pool)


async def check_redis_connection() -> bool:
    try:
        return bool(await get_redis().ping())
    except Exception:
        return False


async def close_redis() -> None:
    await pool.disconnect()
