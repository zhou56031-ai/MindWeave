from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=150)
    email: EmailStr
    password: str = Field(min_length=6, max_length=72)
    confirm_password: str
    telephone: str | None = Field(default=None, max_length=11)


class LoginRequest(BaseModel):
    username: str | None = None
    email: EmailStr | None = None
    # 登录与注册统一 6 位下限：不再为兼容旧练习账号放宽校验。
    password: str = Field(min_length=6, max_length=72)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: str
    user_id: str | None = None
    id: str | None = None
    username: str
    email: EmailStr
    telephone: str | None = None
    gender: int | None = None
    bio: str | None = None
    avatar: str | None = None
    status: int
    date_joined: datetime | None = None
    last_login: datetime | None = None
    is_active: bool


class TokenRefreshRequest(BaseModel):
    token: str = Field(min_length=1)


class UserUpdateRequest(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=150)
    telephone: str | None = Field(default=None, max_length=11)
    gender: int | None = None
    bio: str | None = None
    avatar: str | None = Field(default=None, max_length=255)


class ResetPasswordRequest(BaseModel):
    old_password: str = Field(min_length=6, max_length=72)
    new_password: str = Field(min_length=6, max_length=72)
    confirm_password: str = Field(min_length=6, max_length=72)
