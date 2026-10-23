from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """全部数据库模型共享同一份 metadata。"""
