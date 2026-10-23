# 第 02 篇：建立请求模型、配置入口与统一错误处理

> 日期：2026-10-20。新版连续教程；面向有 Python、HTTP、JSON 与异步基础的读者。 
> 前置：完成[上一篇](01-backend-entry-and-health.md)，从该篇最终文件继续。 
> 本篇成果：给输入数据和错误响应建立边界，为真实创建笔记做准备。 
> 交付范围：本篇是操作教材，代码在独立临时目录验证；不会自动把新增代码写入你的正式复刻目录。

**技术路线原理与同类比较：** [Q03：Pydantic 与 dataclass、手工校验](technology-routes/Q03-pydantic-validation.md)。

## 1. 本篇目标与操作起点

复刻根目录固定为：

```text
.
```

文中所有 backend/、app/ 等位置都以这里为准，不在上一级参考项目中写代码。用户当前正式项目只执行到新版第 01 篇；本篇及后续篇章需要按顺序完成，不能直接跳到最后一篇复制入口文件。

本篇保留现有健康路由和成功响应。新增 schemas 包与 NoteCreate，新增配置读取及错误处理文件，最后修改 main.py 接入。暂不增加假装落库的创建接口；真正的 POST /note/create 在第 04 篇接入数据库后实现。

基础语法直接使用。本篇围绕正在创建的文件说明职责、数据与调用关系，重点解释新机制和为什么这样组织。
## 2. 文件变化与执行顺序

| 标记 | 文件或目录 | 本篇用途 |
|---|---|---|
| 【新增文件夹】 | backend/app/schemas/ | HTTP 输入输出数据模型 |
| 【新增文件】 | app/schemas/__init__.py、models.py | 包标识与创建笔记请求规则 |
| 【新增文件】 | app/core/settings.py | 配置唯一读取点 |
| 【新增文件】 | 复刻根目录 .env.example | 可提交的本机配置示例 |
| 【新增文件】 | app/core/failed_response.py | 错误响应与业务异常类型 |
| 【新增文件】 | app/core/failed_response_register.py | 将处理器挂入 FastAPI |
| 【修改】 | backend/main.py | 读取应用名并注册异常处理器 |
| 【工具生成】 | pyproject.toml、uv.lock、requirements.txt | 新增 pydantic-settings 并同步锁定结果 |

本篇统一采用 code、message、data 的响应外壳。HTTP 404/405/422 保留协议状态；显式业务异常沿用参考代码的“HTTP 200 + 业务 code”约定。不要把这两类混为一谈。

## 3. 按顺序创建文件

先在 backend 安装配置读取库并创建目录。下面命令不重建虚拟环境：
```bash
cd "./backend"
uv add "pydantic-settings==2.13.1"
uv export --locked --no-dev --no-emit-project --no-hashes --format requirements.txt --output-file requirements.txt
mkdir -p app/schemas
```
pydantic-settings 的版本对照参考项目。uv add 同时更新声明、锁文件和本机安装结果，导出命令再更新 requirements.txt；不要只往 requirements.txt 手写一行却让运行环境保持旧状态。

接下来逐个保存文件，直到 main.py 的修改也完成后再运行。开发服务若开启自动重载，保存中途可能短暂看到导入失败，待关联文件齐全后再检查。
### 步骤 1：【新增文件】 `backend/app/schemas/__init__.py`

**编辑文件的完整地址：**

```text
./backend/app/schemas/__init__.py
```

**新建说明：** 先确认父目录已按本篇命令创建，再新建同名文件；整个文件都是本步新增内容。

**完整文件内容：**

<!-- file: backend/app/schemas/__init__.py -->
```python
"""HTTP 输入与输出的数据模型。"""
```

**文件职责：** 组织后续请求与响应模型；这里只放包说明，不在导入时创建数据或执行请求。这个目录和 models 目录将分工：schemas 描述接口数据，后续 models 描述数据库表。两者都可能叫“模型”，但作用不同。

### 步骤 2：【新增文件】 `backend/app/schemas/models.py`

**编辑文件的完整地址：**

```text
./backend/app/schemas/models.py
```

**新建说明：** 先确认父目录已按本篇命令创建，再新建同名文件；整个文件都是本步新增内容。

**完整文件内容：**

<!-- file: backend/app/schemas/models.py -->
```python
from pydantic import BaseModel, Field, field_validator


class NoteCreate(BaseModel):
    # 【新增】先处理首尾空白，再检查标题长度。
    title: str = Field(min_length=1, max_length=200)
    content: str
    category: str | None = Field(default=None, max_length=50)
    tags: list[str] | None = None

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value):
        return value.strip() if isinstance(value, str) else value
```

关于 Field、必填/可空、before 与 cls 的逐段解释，见本次[专项问答 Q004](../03-knowledge-q-and-a.md#q004)。

**文件作用：** 表达“创建笔记时调用方要提交哪些字段”，现在就建立与原项目相同的 title、content、category、tags 字段名，后面路由直接复用。

**关键代码：** 把 NoteCreate 看作接收材料的规格表。原始 JSON 变成 Python 数据后，Pydantic 按规格表构造对象；构造失败时就不该让这份数据继续进入数据库写入。

`Field` 给标题加了 1–200 字符的约束，分类限制到 50 字符，与数据库列容量配合。`mode="before"` 让标题先去除首尾空白，再执行长度检查。因此三个空格不是合法标题，而“  学习 RAG  ”成为“学习 RAG”。非字符串不强行转换，让后续类型检查报出真实问题。

正文没有 strip：Markdown 正文的缩进可能有意义，不能为了“清洗”抹掉内容。空正文当前仍允许，与参考请求结构一致。tags 未提供或明确为 null 都保留 None，由后续服务决定存储值。

**与参考的边界：** 字段名保持一致；参考 NoteCreate 主要声明类型，本篇额外提前检查标题和分类长度，并整理标题空白。这是明确的输入约束增强，后续前端联调时需核对错误契约；不把额外规则说成原源码逐行照搬。暂不配置 extra="forbid"，未声明字段按 Pydantic 默认策略忽略。

**当前阶段：** 这里只定义模型，不创建笔记、不写文件、不连接数据库。真正的请求路由使用该类型后，HTTP 请求校验才会自动接上。

### 步骤 3：【新增文件】 `backend/app/core/settings.py`

**编辑文件的完整地址：**

```text
./backend/app/core/settings.py
```

**新建说明：** 先确认父目录已按本篇命令创建，再新建同名文件；整个文件都是本步新增内容。

**完整文件内容：**

<!-- file: backend/app/core/settings.py -->
```python
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# 【新增】从本文件定位复刻根目录，不受终端当前目录影响。
REBUILD_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REBUILD_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "RAGNotebook Rebuild"
    ENV: Literal["dev", "test", "prod"] = "dev"


settings = Settings()
```

**文件职责：** 所有模块统一从这里拿配置，避免每个文件各自读取环境变量、默认值不一致。

`REBUILD_ROOT` 从 app/core/settings.py 向上定位三层父目录后的复刻根目录。例如这个文件位于 rebuild/backend/app/core，parents[0] 是 core，parents[1] 是 app，parents[2] 是 backend，parents[3] 才是 rebuild。不能凭“数三个目录”的口头描述改错下标。

`Settings()` 相当于把默认配置、.env 文件和进程环境变量汇总成一份运行配置。普通同名配置中，进程环境变量优先于 .env，.env 优先于类里的默认值；后面临时测试环境不需要修改文件。

`ENV` 使用 Literal，拼错环境名会在配置构造时直接失败。模块首次导入时产生 settings；之后只改 .env 不会自动让已创建的对象重新读文件，要重启应用。不要向外暴露整份 settings，后面会包含数据库口令。

`extra="ignore"` 让同一个根 .env 将来可兼供 Docker Compose 和后端使用，后端忽略自己不认识的配置项。它与 NoteCreate 的输入规则属于不同层。

### 步骤 4：【新增文件】 `.env.example`

**编辑文件的完整地址：**

```text
./.env.example
```

**新建说明：** 先确认父目录已按本篇命令创建，再新建同名文件；整个文件都是本步新增内容。

**完整文件内容：**

<!-- file: .env.example -->
```dotenv
APP_NAME=RAGNotebook Rebuild
ENV=dev
```

**文件职责：** 提供可以提交到 Git 的配置样板，当前只有非敏感设置。真正的 .env 已在第 01 步的忽略规则中排除。

**操作位置：复刻根目录。** 第一次创建本地配置时执行下面命令；-n 表示同名目标已存在就不覆盖。已有 .env 时在编辑器中对照补充字段，保留已有内容。

```bash
cd "."
cp -n .env.example .env
```
### 步骤 5：【新增文件】 `backend/app/core/failed_response.py`

**编辑文件的完整地址：**

```text
./backend/app/core/failed_response.py
```

**新建说明：** 先确认父目录已按本篇命令创建，再新建同名文件；整个文件都是本步新增内容。

**完整文件内容：**

<!-- file: backend/app/core/failed_response.py -->
```python
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
```

**文件职责：** 只定义“遇到不同错误时怎样构造响应”，还没有把这些规则注册到主应用。

**业务异常与 HTTP 异常分开：** BusinessException 表示代码主动拒绝某个业务操作，例如后面“没有提交任何可修改字段”。这是项目约定，所以 HTTP 可能是 200，正文 code 却是 4001。客户端必须同时理解协议状态和业务状态。

HTTPException 则表达路径、方法或访问规则问题，本处理器保留 exc.status_code。使用 Starlette 的基类，既能处理框架自动产生的 404/405，也能处理 FastAPI 抛出的子类异常。若只注册在错误的异常类型上，统一外壳可能只对部分错误生效。

保留 `headers=exc.headers` 是因为某些错误携带重要响应头，例如 405 的 Allow。统一格式不应悄悄丢掉协议信息。

请求校验错误不是一段任意字符串。这里从每条错误提取 loc、type、message，loc 能定位到 body/title 或 query/page。我们不回显原始输入，避免错误响应中带回正文或后续凭据。这里没有捕获所有 Exception；未知程序错误仍应暴露在服务日志供开发排查，不能伪装成一次正常业务拒绝。

**异常传播路径：** 抛出异常 → FastAPI 查找已注册处理器 → 处理器生成 JSONResponse。定义类和函数不会自动修改 FastAPI 的行为，还需要下一个注册文件。

### 步骤 6：【新增文件】 `backend/app/core/failed_response_register.py`

**编辑文件的完整地址：**

```text
./backend/app/core/failed_response_register.py
```

**新建说明：** 先确认父目录已按本篇命令创建，再新建同名文件；整个文件都是本步新增内容。

**完整文件内容：**

<!-- file: backend/app/core/failed_response_register.py -->
```python
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
```

**文件作用：** 将“错误类型 → 处理函数”交给应用。它和你问过的 include_router 很像：前者登记异常处理规则，后者登记路由处理规则。

参数位置放的是函数对象，没有写 business_exception_handler(...)，因此注册时不会伪造一次错误请求。等请求处理阶段真的出现相应异常，框架才调用它。

把注册单独组织成函数，入口只需要一行就能挂载全部规则。后续引入 SQLAlchemy 错误时可以继续在这里加登记，不需要把每个路由都套一遍 try/except。

### 步骤 7：【修改】`backend/main.py`

**编辑文件的完整地址：**

```text
./backend/main.py
```

**修改定位与前后对照：** 根据下列函数名、配置项或导入位置定位；diff 仅供阅读，正负号不要复制进源码。对照以完成上一篇后的版本为准，请按 diff 修改已有文件。

```diff
--- backend/main.py（修改前）
+++ backend/main.py（修改后）
@@ -1,12 +1,15 @@
 from fastapi import FastAPI
 
+from app.core.failed_response_register import register_exception_handlers
+from app.core.settings import settings
 from app.router.health import health_router
 
-# 【新增】创建整个后端的应用对象。
-app = FastAPI()
+# 【修改 C01】应用元信息来自统一配置入口。
+app = FastAPI(title=settings.APP_NAME)
 
-# 【新增】把健康路由组的规则接入主应用。
 app.include_router(health_router)
+# 【新增 C02】让自定义错误处理器真正进入应用。
+register_exception_handlers(app)
 
 
 @app.get("/")
```

**整体解释：** 主应用像接待大厅：settings 给大厅挂上统一名称，register_exception_handlers 把错误处理规则接到总台。请求仍由 FastAPI 分发；出错时才会由处理器整理成约定的响应，因此配置、路由和错误出口在同一个入口接通。C01 增加 settings 导入并用 APP_NAME 创建应用；C02 导入并调用注册函数。原来的四个接口保持可用，include_router 的作用不变。导入 main → 构造 settings → 创建 app → 注册路由和异常处理器。配置不合法可能在服务监听之前就导致启动失败；这不是某个 HTTP 请求的 422，因为请求根本还没到来。比如访问不存在的地址，框架产生 404，处理器将它包装为 code、message、data，HTTP 仍为 404。不要把“统一 JSON 格式”理解为“一切都变成成功”。

## 4. 连起来看一个输入怎样被检查

使用标题“  第一篇笔记  ”、正文“保留 Markdown 格式”、空分类和两个标签时，NoteCreate 先整理标题，再构造模型对象。`model_dump()` 是交给后续服务的 Python 数据，不等于把数据存进数据库。

此时还没有创建接口，所以先直接调用模型观察规则。**执行位置：复刻 backend。**
```bash
cd "./backend"
```
```bash
uv run python - <<'PYCODE'
from pydantic import ValidationError
from app.schemas.models import NoteCreate

note = NoteCreate(title="  第一篇笔记  ", content="保留 Markdown 格式", tags=["学习", "RAG"])
print(note.model_dump())
for payload in [
    {"title": "   ", "content": "正文"},
    {"title": "字" * 201, "content": "正文"},
    {"title": "缺少正文"},
]:
    try:
        NoteCreate.model_validate(payload)
    except ValidationError as error:
        first = error.errors()[0]
        print(first["loc"], first["type"])
PYCODE
```
你应看到规范化标题和三条校验错误，分别对应过短、过长和缺少字段。这次是直接构造模型，所以捕获的是 Pydantic ValidationError；后面 FastAPI 在 HTTP 参数转换阶段使用同一模型，才会产生 RequestValidationError 并进入自定义 422 处理器。

## 5. 启动与验证

若 8100 已运行本项目，保存全部文件后等待重载；若未运行，在终端 A 执行：
```bash
cd "./backend"
uv run uvicorn main:app --reload --host 127.0.0.1 --port 8100
```
**执行位置：新终端 B，任意目录。**
```bash
curl -i http://127.0.0.1:8100/not-found
curl -i -X POST http://127.0.0.1:8100/health/live
curl -i http://127.0.0.1:8100/health/live
```
三个结果分别应为：HTTP 404 且正文包含 code=404；HTTP 405 且保留 Allow 响应头；HTTP 200 且健康响应结构与第 01 篇相同。

404 正文示例：
```json
{"code":404,"message":"Not Found","data":null}
```
**配置检查：** 在 backend 执行 `uv run python -c 'from app.core.settings import settings; print(settings.APP_NAME, settings.ENV)'`，不打印整份配置。要验证环境覆盖，可在另一个命令前加 `ENV=test`；测试非法值时用 `ENV=invalid`，预期命令失败。不要把一次失败测试留下的环境变量永久写入 Shell 配置。

**停止方式：** 手动启动的终端 A 按 Control + C；新开终端运行服务时依然从 backend 进入。改 .env 后应手动重启，不把自动源码重载当作配置文件监控器。

## 6. 常见问题与定位

| 现象 | 从哪里检查 | 为什么 |
|---|---|---|
| No module named pydantic_settings | backend 的 uv run 与 uv sync --locked | 安装位置或环境不一致 |
| .env 已改但 APP_NAME 未变 | .env 是否在复刻根目录、是否有同名进程环境变量、是否重启 | 配置有优先级且不是每次请求重读 |
| 404 还是默认 detail 外壳 | main 是否调用 register_exception_handlers，是否访问 8100 | 文件定义不等于应用已注册 |
| NoteCreate 明明有标注却没有执行检查 | 是否实例化模型而非普通字典 | 约束必须经过模型构造过程 |
| 看到 HTTP 200 就认为业务成功 | 正文 code | 业务错误沿用项目的另一层状态约定 |

## 7. 做完后核对与下一步

- [ ] 新文件路径正确，入口从第 01 篇替换为本篇最终内容。
- [ ] 请求模型能整理标题并拒绝示例中的非法输入。
- [ ] 404/405 使用统一外壳，健康接口仍正常。
- [ ] pyproject.toml、uv.lock 与 requirements.txt 已同步。
- [ ] .env 只保存在本机；.env.example 保留在源码里。

当前没有数据库和真实创建笔记。下一篇[MySQL 与异步会话](03-mysql-and-async-session.md)会建立落库基础，再让第 04 篇真正提供 POST /note/create。接口校验代码在那时直接复用，本篇不另造一个之后必须删除的演示保存接口。

**参考源码：** [请求模型](../../../backend/app/schemas/models.py)、[配置中心](../../../backend/app/core/settings.py)、[异常注册](../../../backend/app/core/failed_response_register.py)。参考文件是上一级项目，只读对照。

### 本篇验证记录

**已执行 Python 与真实 HTTP 验证（2026-10-20，临时独立环境）**：Python 3.12.13 与教程指定依赖安装成功；NoteCreate 标题整理、过短/过长和缺少字段检查通过；非法 ENV 会在配置构造时报错；HTTP 404/405 统一外壳、Allow 响应头和健康回归通过。本篇没有数据库操作，也没有给正式复刻项目安装新增依赖。

本轮临时验证记录：`/tmp/verification-results.json`。所有验证服务均已停止；正式 8100 服务及其源码不参与本轮变更。
