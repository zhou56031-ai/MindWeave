from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, Text, func

from app.models.base import Base


class NoteTemplate(Base):
    __tablename__ = "note_templates"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), index=True, nullable=False)
    name = Column(String(100), nullable=False)
    icon = Column(String(50), default="FileText", nullable=False)
    category = Column(String(50), default="", nullable=False)
    title = Column(String(200), default="", nullable=False)
    content = Column(Text, default="", nullable=False)
    tags = Column(JSON, default=list, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(), server_default=func.now(), onupdate=func.now(), nullable=False)
