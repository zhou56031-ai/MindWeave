import time
from uuid import uuid4

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.db.db_config import get_db
from app.db.redis_config import get_redis
from app.models.user_model import User, UserStatusChoice

security = HTTPBearer(auto_error=False)


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> str:
    if credentials is None:
        raise HTTPException(status_code=401, detail="缺少 Bearer token")
    payload = decode_token(credentials.credentials)
    if payload is None or not isinstance(payload.get("user_id"), str):
        raise HTTPException(status_code=401, detail="Token 无效或已过期")
    jti = payload.get("jti")
    if not isinstance(jti, str):
        raise HTTPException(status_code=401, detail="Token 缺少编号")
    try:
        if await get_redis().exists(f"blacklist:{jti}"):
            raise HTTPException(status_code=401, detail="Token 已注销")
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="令牌状态暂不可用") from exc
    user_id = payload["user_id"]
    result = await db.execute(select(User).where(User.uuid == user_id))
    user = result.scalar_one_or_none()
    if user is None or user.status != UserStatusChoice.ACTIVE or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或不可用")
    return user.uuid


def generate_token(user_id: str, username: str, email: str) -> tuple[str, int]:
    now = int(time.time())
    expires_at = now + 24 * 60 * 60
    token = jwt.encode(
        {"user_id": user_id, "username": username, "email": email,
         "iat": now, "exp": expires_at, "jti": str(uuid4())},
        settings.SECRET_KEY.get_secret_value(),
        algorithm=settings.ALGORITHM,
    )
    return token, expires_at


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(
            token,
            settings.SECRET_KEY.get_secret_value(),
            algorithms=[settings.ALGORITHM],
        )
    except JWTError:
        return None


async def blacklist_token(token: str) -> None:
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")
    jti, exp = payload.get("jti"), payload.get("exp")
    if not isinstance(jti, str) or not isinstance(exp, int):
        raise HTTPException(status_code=401, detail="Token 缺少必要字段")
    ttl = max(exp - int(time.time()), 1)
    try:
        await get_redis().set(f"blacklist:{jti}", "1", ex=ttl)
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="注销暂不可用") from exc


async def consume_token(token: str) -> dict:
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")
    jti, exp = payload.get("jti"), payload.get("exp")
    if not isinstance(jti, str) or not isinstance(exp, int):
        raise HTTPException(status_code=401, detail="Token 缺少必要字段")
    ttl = max(exp - int(time.time()), 1)
    try:
        first_use = await get_redis().set(f"blacklist:{jti}", "1", ex=ttl, nx=True)
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="令牌刷新暂不可用") from exc
    if not first_use:
        raise HTTPException(status_code=401, detail="Token 已使用或注销")
    return payload
