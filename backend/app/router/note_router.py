from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.success_response import success_response
from app.db.db_config import get_db
from app.rag.related import related_fragments
from app.schemas.models import (
    AutocompleteRequest,
    BatchCategoryRequest, BatchIdsRequest, BatchPinRequest,
    NoteCreate, NoteListResponse, NoteResponse, NoteUpdate,
)
from app.services.note_ai_service import note_ai_service
from app.services.note_service import note_service
from app.utils.auth_utils import get_current_user_id

note_router = APIRouter(prefix="/note", tags=["note"])


class AssistRequest(BaseModel):
    content: str = Field(min_length=1, max_length=6000)
    action: Literal["continue", "expand", "summarize"] = "continue"


@note_router.post("/create")
async def create_note(
    payload: NoteCreate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    note = await note_service.create_note(db, user_id, payload)
    return success_response(message="笔记创建成功", data=NoteResponse.model_validate(note))


@note_router.get("/list")
async def list_notes(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    category: str | None = Query(default=None, max_length=50),
    tag: str | None = Query(default=None, min_length=1, max_length=50),
    sort_by: Literal["updated_at", "created_at", "title"] = "updated_at",
) -> JSONResponse:
    # 【修改 C02】接收服务返回的当前页和筛选总数，二者不要混淆。
    notes, total_count = await note_service.list_notes(
        db, user_id, page, page_size, category, tag, sort_by
    )
    data = NoteListResponse(
        notes=[NoteResponse.model_validate(note) for note in notes],
        total_count=total_count,
    )
    return success_response(data=data)


@note_router.post("/batch/delete")
async def batch_delete_notes(
    payload: BatchIdsRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    deleted = await note_service.batch_delete_notes(db, user_id, payload.ids)
    return success_response(message=f"成功删除 {deleted} 篇笔记")


@note_router.put("/batch/pin")
async def batch_pin_notes(
    payload: BatchPinRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    updated = await note_service.batch_pin_notes(
        db, user_id, payload.ids, payload.is_pinned
    )
    return success_response(message=f"成功更新 {updated} 篇笔记的置顶状态")


@note_router.put("/batch/category")
async def batch_update_category(
    payload: BatchCategoryRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    updated = await note_service.batch_update_category(
        db, user_id, payload.ids, payload.category
    )
    return success_response(message=f"成功更新 {updated} 篇笔记的分类")


@note_router.delete("/category/{category}")
async def delete_category(
    category: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    deleted = await note_service.delete_category(db, user_id, category)
    return success_response(
        message=f"成功删除分类「{category}」及其 {deleted} 篇笔记",
        data={"deleted_count": deleted},
    )


@note_router.post("/batch/download")
async def batch_download_notes(
    payload: BatchIdsRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    data = await note_service.batch_export_zip(db, user_id, payload.ids)
    return Response(
        content=data, media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="notes.zip"'},
    )


@note_router.get("/{note_id}/download")
async def download_note(
    note_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    markdown = await note_service.export_note_markdown(db, user_id, note_id)
    if markdown is None:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return Response(
        content=markdown.encode("utf-8"), media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{note_id}.md"'},
    )


@note_router.get("/{note_id}/export")
async def export_note(
    note_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    markdown = await note_service.export_note_markdown(db, user_id, note_id)
    if markdown is None:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return Response(
        content=markdown.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
    )


@note_router.get("/{note_id}/related")
async def related_note_fragments(
    note_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return success_response(data=await related_fragments(db, user_id, note_id))


@note_router.post("/autocomplete")
async def autocomplete(
    payload: AutocompleteRequest,
    user_id: str = Depends(get_current_user_id),
) -> JSONResponse:
    return success_response(data=await note_ai_service.autocomplete(payload.context))


@note_router.post("/assist/stream")
async def assist_stream(
    payload: AssistRequest,
    user_id: str = Depends(get_current_user_id),
) -> StreamingResponse:
    async def events():
        try:
            async for part in note_ai_service.assist_chunks(
                payload.content, payload.action,
            ):
                for line in part.splitlines(keepends=True):
                    yield "data: " + line.replace("\n", "") + "\n\n"
            yield "data: [DONE]\n\n"
        except Exception:
            yield "data: [ERROR: 模型写作暂不可用]\n\n"

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@note_router.get("/search")
async def search_notes(
    q: str = Query(min_length=1, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    notes, total = await note_service.search_notes(db, user_id, q, page, page_size)
    return success_response(data=NoteListResponse(
        notes=[NoteResponse.model_validate(note) for note in notes],
        total_count=total,
    ))


@note_router.get("/stats")
async def get_note_stats(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    # 【新增】统计只看当前令牌所属用户的笔记。
    return success_response(data=await note_service.get_category_stats(db, user_id))


@note_router.get("/{note_id}")
async def get_note(
    note_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    note = await note_service.get_note(db, note_id, user_id)
    if note is None:
        return success_response(message="笔记不存在")
    return success_response(data=NoteResponse.model_validate(note))


@note_router.put("/{note_id}")
async def update_note(
    note_id: str,
    payload: NoteUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    # 【新增 C03】HTTP 参数与依赖准备好后，交给服务完成修改。
    note = await note_service.update_note(db, note_id, user_id, payload)
    if note is None:
        return success_response(message="笔记不存在")
    return success_response(message="笔记更新成功", data=NoteResponse.model_validate(note))


@note_router.put("/{note_id}/pin")
async def toggle_pin(
    note_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    note = await note_service.toggle_pin(db, note_id, user_id)
    if note is None:
        return success_response(message="笔记不存在")
    return success_response(message="置顶已更新", data=NoteResponse.model_validate(note))


@note_router.post("/{note_id}/auto-tag")
async def regenerate_tags(
    note_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    data = await note_ai_service.auto_tag(db, user_id, note_id)
    return success_response(message="标签已更新", data=data)


@note_router.delete("/{note_id}")
async def delete_note(
    note_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    deleted = await note_service.delete_note(db, note_id, user_id)
    if not deleted:
        return success_response(message="笔记不存在")
    return success_response(message="笔记删除成功")
