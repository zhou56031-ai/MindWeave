"""回顾页面的 HTTP 接口。"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.success_response import success_response
from app.db.db_config import get_db
from app.services.review_service import review_service
from app.utils.auth_utils import get_current_user_id

review_router = APIRouter(prefix="/review", tags=["review"])


@review_router.get("/today")
async def get_today_reviews(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return success_response(data=await review_service.today(db, user_id))


@review_router.post("/done/{note_id}")
async def mark_reviewed(
    note_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await review_service.mark_done(db, user_id, note_id)
    return success_response(message="已标记回顾", data=result)


@review_router.get("/question/{note_id}")
async def get_review_question(
    note_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return success_response(data=await review_service.question(db, user_id, note_id))
