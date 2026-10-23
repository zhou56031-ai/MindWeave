from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.note_template import NoteTemplate
from app.schemas.models import (
    NoteTemplateCreate, NoteTemplateResponse, NoteTemplateReorder,
    NoteTemplateUpdate,
)

DEFAULT_TEMPLATES = [
    ("空白笔记", "FileText", "", "", "", []),
    ("会议纪要", "Users", "work", "会议纪要 - ",
     "## 会议信息\n- 时间：\n- 参与人：\n\n## 待办事项\n- [ ] ", ["会议"]),
    ("学习笔记", "GraduationCap", "study", "",
     "## 学习目标\n\n## 核心内容\n\n## 总结与反思\n", ["学习"]),
    ("日记", "BookOpen", "life", "",
     "## 今日记录\n\n## 心情\n\n## 明日计划\n", ["日记"]),
    ("项目计划", "ListTodo", "project", "",
     "## 项目概述\n\n## 目标\n\n## 里程碑\n", ["项目"]),
    ("读书笔记", "BookMarked", "study", "",
     "## 书籍信息\n\n## 核心观点\n\n## 读后感\n", ["读书"]),
]


class NoteTemplateService:
    async def _seed_defaults(self, db: AsyncSession, user_id: str) -> None:
        for order, (name, icon, category, title, content, tags) in enumerate(DEFAULT_TEMPLATES):
            db.add(NoteTemplate(
                id=str(uuid4()), user_id=user_id, name=name, icon=icon,
                category=category, title=title, content=content,
                tags=tags, is_default=True, sort_order=order,
            ))
        await db.commit()

    async def list_templates(
        self, db: AsyncSession, user_id: str
    ) -> list[NoteTemplateResponse]:
        count = await db.scalar(select(func.count(NoteTemplate.id)).where(
            NoteTemplate.user_id == user_id
        ))
        if not count:
            await self._seed_defaults(db, user_id)
        result = await db.execute(
            select(NoteTemplate).where(NoteTemplate.user_id == user_id)
            .order_by(NoteTemplate.sort_order.asc(), NoteTemplate.created_at.asc())
        )
        return [NoteTemplateResponse.model_validate(item) for item in result.scalars().all()]

    async def create_template(
        self, db: AsyncSession, user_id: str, payload: NoteTemplateCreate
    ) -> NoteTemplateResponse:
        await self.list_templates(db, user_id)
        max_order = await db.scalar(select(func.max(NoteTemplate.sort_order)).where(
            NoteTemplate.user_id == user_id
        ))
        template = NoteTemplate(
            id=str(uuid4()), user_id=user_id, name=payload.name,
            icon=payload.icon, category=payload.category, title=payload.title,
            content=payload.content, tags=payload.tags, is_default=False,
            sort_order=(max_order if max_order is not None else -1) + 1,
        )
        db.add(template)
        await db.commit()
        await db.refresh(template)
        return NoteTemplateResponse.model_validate(template)

    async def update_template(
        self, db: AsyncSession, user_id: str, template_id: str,
        payload: NoteTemplateUpdate,
    ) -> NoteTemplateResponse | None:
        result = await db.execute(select(NoteTemplate).where(
            NoteTemplate.id == template_id, NoteTemplate.user_id == user_id
        ))
        template = result.scalar_one_or_none()
        if template is None:
            return None
        for field, value in payload.model_dump(exclude_unset=True).items():
            if value is not None:
                setattr(template, field, value)
        await db.commit()
        await db.refresh(template)
        return NoteTemplateResponse.model_validate(template)

    async def delete_template(
        self, db: AsyncSession, user_id: str, template_id: str
    ) -> bool:
        result = await db.execute(select(NoteTemplate).where(
            NoteTemplate.id == template_id, NoteTemplate.user_id == user_id
        ))
        template = result.scalar_one_or_none()
        if template is None or template.is_default:
            return False
        await db.delete(template)
        await db.commit()
        return True

    async def reorder_templates(
        self, db: AsyncSession, user_id: str, payload: NoteTemplateReorder
    ) -> bool:
        result = await db.execute(select(NoteTemplate).where(
            NoteTemplate.user_id == user_id
        ))
        templates = {item.id: item for item in result.scalars().all()}
        if len(payload.ids) != len(templates) or set(payload.ids) != set(templates):
            return False
        for order, template_id in enumerate(payload.ids):
            templates[template_id].sort_order = order
        await db.commit()
        return True


note_template_service = NoteTemplateService()
