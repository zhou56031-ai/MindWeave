"""知识库 HTTP 接口。"""

import asyncio
import base64
import json

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.failed_response import BusinessException
from app.core.rate_limit import rate_limit
from app.core.success_response import success_response
from app.core.settings import settings
from app.db.db_config import AsyncSessionLocal, get_db
from app.models.knowledge_document import KnowledgeDocument
from app.services.document_parser import MAX_FILE_BYTES
from app.services.knowledge_service import knowledge_service
from app.services.pdf_vision import image_path
from app.utils.auth_utils import get_current_user_id

knowledge_router = APIRouter(prefix="/knowledge", tags=["knowledge"])
upload_rate_limit = rate_limit(
    "upload",
    settings.RATE_LIMIT_UPLOAD_PER_MINUTE,
)


@knowledge_router.post("/add/multiple/stream")
async def add_multiple_stream(
    files: list[UploadFile] = File(...),
    user_id: str = Depends(get_current_user_id),
    _: None = Depends(upload_rate_limit),
) -> StreamingResponse:
    if len(files) > 5:
        raise HTTPException(status_code=422, detail="一次最多上传 5 个文件")
    pending = []
    for file in files:
        try:
            pending.append((file.filename or "", await file.read(MAX_FILE_BYTES + 1)))
        finally:
            await file.close()

    async def events():
        total = len(pending)
        for current, (filename, raw) in enumerate(pending, start=1):
            yield "data: " + json.dumps({
                "event_type": "processing", "filename": filename,
                "progress": 10, "current": current, "total": total,
            }, ensure_ascii=False) + "\n\n"
            try:
                # 【新增】流开始后逐文件新建会话，失败只影响当前文件。
                async with AsyncSessionLocal() as db:
                    await knowledge_service.add_document(db, user_id, filename, raw)
            except BusinessException as exc:
                yield "data: " + json.dumps({
                    "event_type": "error", "filename": filename,
                    "error_message": exc.message, "current": current, "total": total,
                }, ensure_ascii=False) + "\n\n"
            except Exception:
                yield "data: " + json.dumps({
                    "event_type": "error", "filename": filename,
                    "error_message": "文件处理失败", "current": current, "total": total,
                }, ensure_ascii=False) + "\n\n"
            else:
                yield "data: " + json.dumps({
                    "event_type": "completed", "filename": filename,
                    "progress": 100, "current": current, "total": total,
                }, ensure_ascii=False) + "\n\n"
        yield 'data: {"event_type":"finish"}\n\n'

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@knowledge_router.post("/add/multiple")
async def add_multiple_documents(
    files: list[UploadFile] = File(...),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(upload_rate_limit),
) -> JSONResponse:
    if len(files) > 5:
        raise HTTPException(status_code=422, detail="一次最多上传 5 个文件")
    names = []
    try:
        for file in files:
            raw = await file.read(MAX_FILE_BYTES + 1)
            document = await knowledge_service.add_document(
                db, user_id, file.filename or "", raw,
            )
            names.append(document.filename)
    finally:
        for file in files:
            await file.close()
    return success_response(
        message="多文件导入成功", data={"filenames": names},
    )


@knowledge_router.post("/add/single")
async def add_single_document(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(upload_rate_limit),
) -> JSONResponse:
    try:
        raw = await file.read(MAX_FILE_BYTES + 1)
        document = await knowledge_service.add_document(
            db, user_id, file.filename or "", raw
        )
    finally:
        await file.close()
    return success_response(message="文档导入成功", data=document)


@knowledge_router.get("/list")
async def list_documents(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    data = await knowledge_service.list_documents(db, user_id)
    return success_response(data=data)


@knowledge_router.get("/detail")
async def get_document_detail(
    filename: str = Query(min_length=1),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    detail = await knowledge_service.get_detail(db, user_id, filename)
    if detail is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return success_response(data=detail)


@knowledge_router.get("/chunks")
async def get_document_chunks(
    filename: str = Query(min_length=1),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    chunks = await knowledge_service.get_chunks(db, user_id, filename)
    if chunks is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return success_response(data=chunks)


@knowledge_router.get("/md5/list")
async def list_md5_records(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return success_response(data=await knowledge_service.list_md5(db, user_id))


@knowledge_router.get("/md5/{md5_value}")
async def get_md5_record(
    md5_value: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    row = await knowledge_service.get_md5(db, user_id, md5_value)
    if row is None:
        raise HTTPException(status_code=404, detail="MD5 记录不存在")
    return success_response(data=row)


@knowledge_router.delete("/md5/clear")
async def clear_md5_records(
    delete_documents: bool = True,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    count = await knowledge_service.clear_md5(db, user_id, delete_documents)
    return success_response(message=f"已清理 {count} 条记录")


@knowledge_router.delete("/delete/filename")
async def delete_by_filename(
    filename: str = Query(min_length=1),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not await knowledge_service.delete_document(db, user_id, filename):
        raise HTTPException(status_code=404, detail="文档不存在")
    return success_response(message="文档及切片已删除")


@knowledge_router.delete("/md5/delete/{md5_value}")
async def delete_by_md5(
    md5_value: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not await knowledge_service.delete_by_md5(db, user_id, md5_value):
        raise HTTPException(status_code=404, detail="文档不存在")
    return success_response(message="文档及切片已删除")


@knowledge_router.delete("/clean")
async def clean_knowledge(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    deleted = await knowledge_service.clean_all(db, user_id)
    return success_response(message=f"成功删除 {deleted} 份文档")


@knowledge_router.get("/image/{md5_value}/{filename}")
async def get_pdf_image(
    md5_value: str,
    filename: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    owned = await db.scalar(select(KnowledgeDocument.id).where(
        KnowledgeDocument.user_id == user_id,
        KnowledgeDocument.md5 == md5_value,
    ))
    path = image_path(user_id, md5_value, filename)
    if owned is None or not path.is_file():
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(path, media_type="image/png")


@knowledge_router.get("/images/all/{md5_value}")
async def get_all_document_images(
    md5_value: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    owned = await db.scalar(select(KnowledgeDocument.id).where(
        KnowledgeDocument.user_id == user_id,
        KnowledgeDocument.md5 == md5_value,
    ))
    if owned is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    root = image_path(user_id, md5_value, "page-1.png").parent
    images = []
    if root.is_dir():
        paths = sorted(
            root.glob("page-*.png"),
            key=lambda path: int(path.stem.split("-", 1)[1]),
        )
        contents = await asyncio.gather(*(
            asyncio.to_thread(path.read_bytes) for path in paths
        ))
        for path, content in zip(paths, contents):
            images.append({
                "filename": path.name,
                "data_url": "data:image/png;base64,"
                + base64.b64encode(content).decode("ascii"),
            })
    return success_response(data={"md5": md5_value, "images": images})
