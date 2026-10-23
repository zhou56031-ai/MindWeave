from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.core.success_response import success_response
from app.db.db_config import check_mysql_connection
from app.db.redis_config import check_redis_connection

health_router = APIRouter(prefix="/health")


@health_router.get("/live", tags=["健康检查"], summary="健康检查")
async def get_health_application_status() -> JSONResponse:
    return success_response(
        message="health application status",
        data={"status": "ok"},
    )


@health_router.get("/ready", tags=["健康检查"], summary="数据库就绪检查")
async def get_health_readiness() -> JSONResponse:
    # 【新增 C01】能接请求与能连接业务依赖，是两种不同状态。
    if not await check_mysql_connection():
        raise HTTPException(status_code=503, detail="MySQL连接失败")
    if not await check_redis_connection():
        raise HTTPException(status_code=503, detail="Redis连接失败")
    return success_response(
        message="health readiness status",
        data={"status": "ok"},
    )
