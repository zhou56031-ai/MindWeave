from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


def success_response(message: str = "success", data=None) -> JSONResponse:
    # 【新增】把不同业务的结果装进同一种响应结构。
    response = {
        "code": 200,
        "message": message,
        "data": data,
    }
    # 【新增】先整理为可编码的数据，再构造实际 HTTP 响应。
    return JSONResponse(content=jsonable_encoder(response))
