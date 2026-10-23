"""基于 Redis 固定窗口的请求限流。"""

import time
from collections.abc import Awaitable, Callable
from ipaddress import ip_address

from fastapi import HTTPException, Request

from app.core.settings import settings
from app.db.redis_config import get_redis


def _client_address(request: Request) -> str:
    # Compose 的 Nginx 会覆盖 X-Real-IP；后端端口只绑定宿主机回环地址。
    forwarded = request.headers.get("x-real-ip")
    if forwarded:
        try:
            return str(ip_address(forwarded.strip()))
        except ValueError:
            pass
    return request.client.host if request.client else "unknown"


def rate_limit(
    scope: str,
    limit: int,
    window_seconds: int = 60,
) -> Callable[[Request], Awaitable[None]]:
    window = max(1, int(window_seconds))

    async def dependency(request: Request) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        client = _client_address(request)
        window_number = int(time.time()) // window
        key = f"rate_limit:{scope}:{client}:{window_number}"
        try:
            redis = get_redis()
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, window + 1)
            if count > limit:
                raise HTTPException(
                    status_code=429,
                    detail="请求过于频繁，请稍后再试",
                    headers={"Retry-After": str(window)},
                )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="限流服务暂不可用",
            ) from exc

    return dependency
