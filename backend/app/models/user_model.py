from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func

from app.models.base import Base


class UserStatusChoice:
    DISABLED = 0
    ACTIVE = 1
    LOCKED = 2


class User(Base):
    __tablename__ = "user_service"

    uuid = Column(String(36), primary_key=True, default=lambda: uuid4().hex[:24])
    username = Column(String(150), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    telephone = Column(String(11), unique=True, nullable=True)
    password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    status = Column(Integer, default=UserStatusChoice.ACTIVE, nullable=False)
    gender = Column(Integer, nullable=True)
    bio = Column(Text, nullable=True)
    avatar = Column(String(255), nullable=True)
    date_joined = Column(DateTime(), server_default=func.now(), nullable=False)
    last_login = Column(DateTime(), nullable=True)
