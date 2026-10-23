from datetime import UTC, datetime

from passlib.context import CryptContext
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.failed_response import BusinessException
from app.models.user_model import User, UserStatusChoice
from app.schemas.user_schemas import (
    RegisterRequest, ResetPasswordRequest, UserUpdateRequest,
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return pwd_context.verify(password, hashed_password)


class UserService:
    async def register(self, db: AsyncSession, payload: RegisterRequest) -> User:
        if payload.password != payload.confirm_password:
            raise BusinessException(code=4001, message="两次密码不一致")
        conditions = [User.email == str(payload.email)]
        if payload.telephone:
            conditions.append(User.telephone == payload.telephone)
        existing = await db.execute(select(User).where(or_(*conditions)))
        if existing.scalars().first() is not None:
            raise BusinessException(code=4002, message="邮箱或手机号已被注册")

        user = User(
            username=payload.username,
            email=str(payload.email),
            telephone=payload.telephone,
            password=hash_password(payload.password),
            status=UserStatusChoice.ACTIVE,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    async def authenticate(self, db: AsyncSession, username: str | None,
                           email: str | None, password: str) -> User:
        identity = username or email
        if not identity:
            raise BusinessException(code=4001, message="请输入用户名或邮箱")
        result = await db.execute(
            select(User).where(or_(User.username == identity, User.email == identity))
        )
        user = result.scalars().first()
        if user is None or not verify_password(password, user.password):
            raise BusinessException(code=4002, message="用户名或密码错误")
        if user.status != UserStatusChoice.ACTIVE or not user.is_active:
            raise BusinessException(code=4003, message="用户不可登录")
        user.last_login = datetime.now(UTC).replace(tzinfo=None)
        await db.commit()
        await db.refresh(user)
        return user

    async def get_user(self, db: AsyncSession, user_id: str) -> User:
        user = await db.get(User, user_id)
        if user is None:
            raise BusinessException(code=4004, message="用户不存在")
        return user

    async def update_user(
        self, db: AsyncSession, user_id: str, payload: UserUpdateRequest
    ) -> User:
        user = await self.get_user(db, user_id)
        changes = payload.model_dump(exclude_unset=True)
        if "username" in changes and changes["username"] is None:
            raise BusinessException(code=4005, message="用户名不可清空")
        if changes.get("telephone"):
            result = await db.execute(select(User).where(
                User.telephone == changes["telephone"], User.uuid != user_id
            ))
            if result.scalar_one_or_none() is not None:
                raise BusinessException(code=4002, message="手机号已被注册")
        for field, value in changes.items():
            setattr(user, field, value)
        await db.commit()
        await db.refresh(user)
        return user

    async def reset_password(
        self, db: AsyncSession, user_id: str, payload: ResetPasswordRequest
    ) -> User:
        if payload.new_password != payload.confirm_password:
            raise BusinessException(code=4001, message="两次新密码不一致")
        if payload.new_password == payload.old_password:
            raise BusinessException(code=4005, message="新密码不能与旧密码相同")
        user = await self.get_user(db, user_id)
        if not verify_password(payload.old_password, user.password):
            raise BusinessException(code=4002, message="旧密码错误")
        user.password = hash_password(payload.new_password)
        await db.commit()
        await db.refresh(user)
        return user


user_service = UserService()
