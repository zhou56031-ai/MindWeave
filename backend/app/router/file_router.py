"""用户头像上传。"""

import asyncio
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import REBUILD_ROOT
from app.db.db_config import get_db
from app.models.user_model import User
from app.utils.auth_utils import get_current_user_id

file_router = APIRouter(prefix="/file", tags=["file"])
MEDIA_ROOT = REBUILD_ROOT / "media"
ALLOWED = {".png", ".jpg", ".jpeg", ".webp"}


@file_router.post("/upload/")
async def upload_avatar(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(status_code=422, detail="头像只支持 PNG/JPG/WebP")
    raw = await file.read()
    if not raw or len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="头像需非空且不超过 5 MB")
    filename = uuid4().hex + suffix
    target = MEDIA_ROOT / "img" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(target.write_bytes, raw)
    try:
        user = await db.scalar(select(User).where(User.uuid == user_id))
        if user is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        user.avatar = f"/media/img/{filename}"
        await db.commit()
    except Exception:
        await db.rollback()
        target.unlink(missing_ok=True)
        raise
    return {
        "success": True,
        "data": {"url": user.avatar, "alt": "用户头像", "href": user.avatar},
    }
