from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.failed_response import (
    BusinessException,
    business_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)


def register_exception_handlers(app: FastAPI) -> None:
    # 【新增】登记错误类型与处理函数的对应关系；这里不调用处理函数。
    app.add_exception_handler(BusinessException, business_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
