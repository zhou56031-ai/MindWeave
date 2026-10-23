from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.success_response import success_response
from app.db.db_config import get_db
from app.models.user_model import User, UserStatusChoice
from app.schemas.user_schemas import (
    LoginRequest, RegisterRequest, TokenRefreshRequest,
    ResetPasswordRequest, UserResponse, UserUpdateRequest,
)
from app.services.memory_service import memory_service
from app.services.user_service import user_service
from app.utils.auth_utils import (
    blacklist_token, consume_token, decode_token, generate_token,
    get_current_user_id, security,
)

class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=500)


user_router = APIRouter(prefix="/user", tags=["user"])


@user_router.post("/register/")
async def register(
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await user_service.register(db, payload)
    token, _expires_at = generate_token(user.uuid, user.username, user.email)
    return {
        "status": 201,
        "message": f"{user.username} 注册成功",
        "user": UserResponse.model_validate(user).model_dump(mode="json"),
        "token": token,
    }


@user_router.post("/login/")
async def login(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await user_service.authenticate(
        db, payload.username, str(payload.email) if payload.email else None,
        payload.password,
    )
    token, _expires_at = generate_token(user.uuid, user.username, user.email)
    return {
        "message": f"{user.username} 登录成功",
        "user": UserResponse.model_validate(user).model_dump(mode="json"),
        "token": token,
    }


@user_router.get("/memories/")
async def list_memories(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    text, memories = await memory_service.summary(db, user_id)
    return success_response(data={
        "summary": text,
        "count": len(memories),
        "items": [
            {"id": item.id, "content": item.content,
             "created_at": item.created_at.isoformat() if item.created_at else None}
            for item in memories
        ],
    })


@user_router.post("/memories/")
async def create_memory(
    payload: MemoryCreate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    item = await memory_service.add(db, user_id, payload.content)
    return success_response(data={"id": item.id, "content": item.content}, message="已记住")


@user_router.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    removed = await memory_service.remove(db, user_id, memory_id)
    if not removed:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return success_response(message="已删除")


@user_router.post("/logout/")
async def logout(
    _user_id: str = Depends(get_current_user_id),
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    await blacklist_token(credentials.credentials)
    return {"message": "用户注销成功"}


@user_router.post("/refresh-token/")
async def refresh_token(
    payload: TokenRefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    claims = decode_token(payload.token)
    if claims is None or not isinstance(claims.get("user_id"), str):
        raise HTTPException(status_code=401, detail="Token 无效或已过期")
    result = await db.execute(select(User).where(User.uuid == claims["user_id"]))
    user = result.scalar_one_or_none()
    if user is None or user.status != UserStatusChoice.ACTIVE or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或不可用")
    await consume_token(payload.token)
    new_token, expires_at = generate_token(user.uuid, user.username, user.email)
    return {"message": "Token刷新成功", "token": new_token,
            "expire_time": expires_at}


def _user_to_response(user: User) -> dict:
    data = UserResponse.model_validate(user).model_dump(mode="json")
    data["user_id"] = user.uuid
    data["id"] = user.uuid
    return data


@user_router.get("/detail/")
async def get_user_info(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await user_service.get_user(db, user_id)
    return {"success": True, "message": "获取用户详情成功",
            "data": _user_to_response(user)}


@user_router.put("/update/")
async def update_user(
    payload: UserUpdateRequest,
    user_id: str = Depends(get_current_user_id),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await user_service.update_user(db, user_id, payload)
    await blacklist_token(credentials.credentials)
    token, _expires_at = generate_token(user.uuid, user.username, user.email)
    return {"message": "用户信息更新成功", "user": _user_to_response(user),
            "token": token}


@user_router.post("/reset-password/")
async def reset_password(
    payload: ResetPasswordRequest,
    user_id: str = Depends(get_current_user_id),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await user_service.reset_password(db, user_id, payload)
    await blacklist_token(credentials.credentials)
    token, _expires_at = generate_token(user.uuid, user.username, user.email)
    return {"message": "密码重置成功", "token": token}
