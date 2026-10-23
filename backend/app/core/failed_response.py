from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class BusinessException(Exception):
    def __init__(self, code: int = 4001, message: str = "业务处理失败"):
        self.code = code
        self.message = message
        super().__init__(message)


async def business_exception_handler(request: Request, exc: BusinessException):
    # 【新增】参考项目约定：业务失败由正文 code 区分，HTTP 仍为 200。
    return JSONResponse(
        status_code=200,
        content={"code": exc.code, "message": exc.message, "data": None},
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder({
            "code": exc.status_code,
            "message": exc.detail,
            "data": None,
        }),
        headers=exc.headers,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # 【新增】不回传原始输入和校验上下文，保留字段位置、错误类型和提示。
    errors = [
        {"loc": list(error["loc"]), "type": error["type"], "message": error["msg"]}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={"code": 422, "message": "请求参数校验失败", "data": errors},
    )
