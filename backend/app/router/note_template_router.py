from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.success_response import success_response
from app.db.db_config import get_db
from app.schemas.models import (
    NoteTemplateCreate, NoteTemplateReorder, NoteTemplateUpdate,
)
from app.services.note_template_service import note_template_service
from app.utils.auth_utils import get_current_user_id

note_template_router = APIRouter(prefix="/note-template", tags=["note-template"])


@note_template_router.get("/list")
async def list_templates(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    templates = await note_template_service.list_templates(db, user_id)
    return success_response(data=templates)


@note_template_router.post("/create")
async def create_template(
    payload: NoteTemplateCreate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    template = await note_template_service.create_template(db, user_id, payload)
    return success_response(message="模板创建成功", data=template)


@note_template_router.put("/reorder")
async def reorder_templates(
    payload: NoteTemplateReorder,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    ok = await note_template_service.reorder_templates(db, user_id, payload)
    return success_response(message="排序成功" if ok else "排序失败，模板ID不匹配")


@note_template_router.put("/{template_id}")
async def update_template(
    template_id: str,
    payload: NoteTemplateUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    template = await note_template_service.update_template(
        db, user_id, template_id, payload
    )
    if template is None:
        return success_response(message="模板不存在")
    return success_response(message="模板更新成功", data=template)


@note_template_router.delete("/{template_id}")
async def delete_template(
    template_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    deleted = await note_template_service.delete_template(db, user_id, template_id)
    return success_response(message="模板删除成功" if deleted else "模板不存在或为内置模板")
