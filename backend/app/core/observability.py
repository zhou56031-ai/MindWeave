"""请求耗时响应头与基础访问日志。"""

import logging
import time

from fastapi import Request

from app.core.settings import settings

logger = logging.getLogger("mindweave.request")


def configure_logging() -> None:
    level_name = settings.LOG_LEVEL.upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger().setLevel(level)


async def process_time_middleware(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed = (time.perf_counter() - started) * 1000
        logger.exception(
            "request_failed method=%s path=%s status=500 duration_ms=%.1f",
            request.method,
            request.url.path,
            elapsed,
        )
        raise

    elapsed = (time.perf_counter() - started) * 1000
    response.headers["X-Process-Time"] = f"{elapsed / 1000:.4f}"
    logger.info(
        "request_completed method=%s path=%s status=%s duration_ms=%.1f",
        request.method,
        request.url.path,
        response.status_code,
        elapsed,
    )
    return response
