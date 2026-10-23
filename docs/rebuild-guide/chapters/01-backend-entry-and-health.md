# 第 01 篇：创建后端入口，接通第一条请求链路

> 新版教程，第 01 篇；2026-10-20。 
> 起点：复刻目录已有 Python 3.12 虚拟环境和本阶段依赖，应用文件尚未创建。 
> 成果：创建 main.py、统一响应函数和健康检查路由，在 8100 端口访问自己编写的接口。 
> 本篇只新增文件，不修改现有依赖，不连接数据库或模型。以下保留逐步创建过程；现已按你的要求在正式复刻目录代为创建六个文件，完成启动、接口及停止重启验证。

**技术路线原理与同类比较：** [Q01：uv 项目环境](technology-routes/Q01-uv-project-environment.md) · [Q02：FastAPI 与 Flask、Django](technology-routes/Q02-fastapi-web-framework.md)。以下仍按文件操作推进；选型原理集中放在 Q 文档。

## 1. 这一步要做什么

先把后端的“接待流程”建起来：启动入口接收请求，路由找到处理函数，处理函数把结果交给统一响应工具，客户端收到 JSON。

本篇直接沿用参考项目的三个位置：

| 本篇文件 | 对应参考源码 | 职责 |
|---|---|---|
| backend/main.py | [参考 main.py](../../../backend/main.py) | 创建应用、挂载路由、提供基础接口 |
| backend/app/core/success_response.py | [参考响应工具](../../../backend/app/core/success_response.py) | 按 code、message、data 组织响应 |
| backend/app/router/health.py | [参考健康路由](../../../backend/app/router/health.py) | 提供 GET /health/live |

这是原项目正式结构的第一小部分。先接通链路，后续继续增加数据库、身份验证和笔记业务。本篇的健康检查只证明程序能响应，数据库就绪检查在接入数据库后再做。

## 2. 文件变化总览

所有相对路径从下面这个**复刻根目录**算起：

```text
.
```

### 2.1 本次操作清单

| 标记 | 路径 | 操作 |
|---|---|---|
| 【查看】 | backend/pyproject.toml、requirements.txt、uv.lock、.venv | 复用已有环境 |
| 【新增文件夹】 | backend/app/ | 放应用模块 |
| 【新增文件夹】 | backend/app/core/ | 放共享的基础工具 |
| 【新增文件夹】 | backend/app/router/ | 放 HTTP 路由 |
| 【新增文件】 | backend/app/__init__.py | 应用包标识 |
| 【新增文件】 | backend/app/core/__init__.py | 基础工具包标识 |
| 【新增文件】 | backend/app/router/__init__.py | 路由包标识 |
| 【新增文件】 | backend/app/core/success_response.py | 统一成功响应 |
| 【新增文件】 | backend/app/router/health.py | 存活检查路由 |
| 【新增文件】 | backend/main.py | 可启动的应用入口 |

本篇没有旧业务代码需要删除或替换。后续修改这些文件时，会先列出【新增】【修改】【删除】位置，给出前后对照，再给最终代码。

### 2.2 完成后的目录

```text
MindWeave/
├── backend/
│   ├── .python-version          # 已有
│   ├── .venv/                  # 已有，不提交到 Git
│   ├── pyproject.toml          # 已有
│   ├── requirements.txt        # 已有
│   ├── uv.lock                 # 已有
│   ├── main.py                 # 本篇新增
│   └── app/                    # 本篇新增
│       ├── __init__.py
│       ├── core/
│       │   ├── __init__.py
│       │   └── success_response.py
│       └── router/
│           ├── __init__.py
│           └── health.py
├── front/                      # 本篇不变
├── docs/                       # 已有学习记录
├── .gitignore                  # 已有
└── README.md                   # 已有
```

## 3. 按顺序动手

### 步骤 1：【查看】确认进入正确后端

**执行位置：终端 A，任意目录。**

```bash
cd "./backend"
pwd
ls -a
uv run python -c 'import sys, fastapi, uvicorn; print(sys.executable); print(fastapi.__version__, uvicorn.__version__)'
```

确认 pwd 末尾是 `MindWeave/backend`，列表中有 pyproject.toml、uv.lock、requirements.txt 和 .venv。解释器应位于这里的 `.venv/bin/python`；最后显示：

```text
0.123.0 0.21.1
```

本篇统一用 uv run 运行，所以无需先激活。你若希望直接用 python 命令，也可在当前 backend 执行 `source .venv/bin/activate`；只影响这个终端。

本篇不重新运行 uv init、git init，也不安装相同依赖。若看到解释器路径指向上一级参考项目，先纠正执行目录。

### 步骤 2：【新增文件夹】创建应用、工具和路由目录

**执行位置：终端 A，复刻项目 backend。**

```bash
mkdir -p app/core app/router
```

app 是应用代码所在的位置；core 的响应工具后面可以被笔记、用户等接口复用；router 按业务组织 HTTP 入口。它们现在属于同一个后端应用，不是三台独立服务。

接下来在编辑器中打开整个 MindWeave 文件夹，依次创建以下文件。若你已经自行创建同名文件，先比对内容，保留已有改动。

### 步骤 3：【新增文件】写入三个包标识文件

这三个文件只组织包，不在导入时连接数据库或执行其他业务。

**编辑文件的完整地址：**

```text
./backend/app/__init__.py
```

完整内容如下。

<!-- file: backend/app/__init__.py -->
```python
"""RAGNotebook 复刻项目的后端应用模块。"""
```

**编辑文件的完整地址：**

```text
./backend/app/core/__init__.py
```

完整内容如下。

<!-- file: backend/app/core/__init__.py -->
```python
"""供业务模块复用的基础工具。"""
```

**编辑文件的完整地址：**

```text
./backend/app/router/__init__.py
```

完整内容如下。

<!-- file: backend/app/router/__init__.py -->
```python
"""按业务划分的 HTTP 路由。"""
```

文件名是 `__init__.py`，前后各两个下划线。这里不把所有子模块自动导入；后面的文件会明确导入需要的对象，便于看清依赖关系。

### 步骤 4：【新增文件】创建统一成功响应工具

**编辑文件的完整地址：**

```text
./backend/app/core/success_response.py
```



**文件作用：** 所有成功接口都可以把消息和数据交给这个函数，由它输出相同结构，避免每个路由各写一套格式。

**完整内容：**

<!-- file: backend/app/core/success_response.py -->
```python
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
```

**关键代码怎样发挥作用：**

把这个函数看作公共打包台。路由准备的业务数据可能不同，但打包台统一使用三个格子：code 放业务状态，message 放说明，data 放实际结果。

例如稍后健康路由传入 message 为 `health application status`、data 为 `{"status": "ok"}`，这里会组装成：

```json
{"code":200,"message":"health application status","data":{"status":"ok"}}
```

`jsonable_encoder(response)` 在 JSON 序列化前整理数据。当前只有字符串和字典，看起来变化不大；以后响应中出现日期时间或 Pydantic 对象，它能处理常见的编码转换，但并非任意 Python 对象都能直接转换。

`JSONResponse(...)` 构造实际响应，默认 HTTP 状态码为 200。字典里的 code 也是 200，是项目另行定义的业务字段；将来仅修改 code 不会自动改变 HTTP 状态码。

这个工具只负责成功响应的格式，不会保存数据，也不会自动捕获调用方的异常。失败响应和异常处理将在后续功能需要时加入。

### 步骤 5：【新增文件】创建健康检查路由

**编辑文件的完整地址：**

```text
./backend/app/router/health.py
```



**文件作用：** 声明健康检查相关路径，把请求处理与应用入口分开。当前只实现原项目的存活接口，不接入数据库就绪检查。

**完整内容：**

<!-- file: backend/app/router/health.py -->
```python
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.success_response import success_response

# 【新增】这个路由组内的路径统一以 /health 开头。
health_router = APIRouter(prefix="/health")


@health_router.get("/live", tags=["健康检查"], summary="健康检查")
async def get_health_application_status() -> JSONResponse:
    # 【新增】交给公共工具构造与参考项目一致的成功响应。
    return success_response(
        message="health application status",
        data={"status": "ok"},
    )
```

**关键代码怎样发挥作用：**

`health_router` 像一页单独的接待表，这页只记录健康检查相关入口。`prefix="/health"` 加上装饰器里的 `/live`，最终路径是 `/health/live`。

此时规则登记在路由组上，还没交给主应用。下一步必须执行 `app.include_router(health_router)`；否则这个 Python 文件即使存在、函数没有语法错误，主应用仍不会提供该地址。

装饰器登记“匹配 GET /health/live 时调用哪个函数”，模块加载时不会因此立刻执行健康检查。tags 和 summary 用于生成接口文档，路径由 prefix 和装饰器参数共同决定。

请求到达后，函数把状态数据交给刚创建的 success_response，再把它构造的响应交回框架。这就是本篇跨文件的第一次协作：

```text
health.py 提供业务结果
        ↓
success_response.py 组织响应
        ↓
客户端收到统一格式的 JSON
```

这里保留异步路由写法，但没有数据库或网络等待。它不会偷偷探测 MySQL、Redis 或 DeepSeek；返回 ok 的含义只是该入口正常响应。

### 步骤 6：【新增文件】创建可启动的应用入口

**编辑文件的完整地址：**

```text
./backend/main.py
```

注意它在 backend 根目录，与 app 文件夹并列。

**文件作用：** 创建主应用，把健康路由挂进去，并提供参考项目已有的基础接口。后续新增笔记、账号等路由时会修改这个入口。

**完整内容：**

<!-- file: backend/main.py -->
```python
from fastapi import FastAPI

from app.router.health import health_router

# 【新增】创建整个后端的应用对象。
app = FastAPI()

# 【新增】把健康路由组的规则接入主应用。
app.include_router(health_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Hello World"}


@app.get("/hello/{name}")
async def say_hello(name: str) -> dict[str, str]:
    return {"message": f"Hello {name}"}


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"message": "The service is healthy"}
```

**关键代码怎样发挥作用：**

main.py 是总接待台，health.py 是健康业务的接待表。`app = FastAPI()` 创建总台，`app.include_router(health_router)` 把那张表的规则登记进来。启动时的注册工作完成后，总台才能按请求地址找到相应处理函数。

关于“导入了为什么还要 include_router”、路径怎样组合以及没有注册会怎样，见你的[专项问答 Q003](../03-knowledge-q-and-a.md#q003)。

`from app.router.health import health_router` 会沿导入关系加载健康路由和响应工具。因此按本篇顺序先创建它们，再启动入口，就能避免引用不存在的文件。

入口中的三个基础路径也对齐参考 main.py：根路径返回 Hello World；hello 路径把 name 作为路径参数传给函数；`/health` 返回简单健康消息。三个函数直接返回字典，由 FastAPI 组织成 JSON；健康路由里的 `/health/live` 则调用公共工具，返回带 code、message、data 的结构。

这两种健康响应同时存在是参考项目本身的接口设计。本篇保留路径和响应差异，后续不能把它们误当作同一个地址随意替换。

## 4. 连起来看一次执行过程

以访问 `GET /health/live` 为例，区分启动与处理请求两个阶段：

**启动时：**

1. Uvicorn 根据启动参数导入 backend 下的 main 模块。
2. main 导入 health_router，health 又导入 success_response。
3. health 模块创建路由组，登记 /live。
4. main 创建 FastAPI 应用，将路由组接入。
5. Uvicorn 开始提供服务，等待请求。

**请求到达时：**

1. Uvicorn 收到 8100 端口的请求，交给应用对象。
2. FastAPI 匹配 GET /health/live，调用 get_health_application_status。
3. 该函数提供状态数据，调用 success_response。
4. success_response 构造统一结构的 JSONResponse。
5. 响应经 Uvicorn 发回客户端。

文件之间没有互相运行新的服务器；它们被导入同一个应用，共同处理这次请求。具体模块职责清楚后，后续添加业务服务、数据库层时，就能继续沿这条调用链延伸。

## 5. 运行与验证

### 步骤 7：【查看】确认文件已保存

**执行位置：终端 A，复刻项目 backend。以下命令只检查，不修改应用源码。**

```bash
ls app/core app/router
uv run python -c 'from main import app; print(app.title); print([route.path for route in app.routes])'
```

输出的路由列表应包括 `/`、`/hello/{name}`、`/health`、`/health/live`，以及 FastAPI 自动提供的文档路径。

如果缺少 `/health/live`，先检查 main.py 中是否保存了 include_router 那一行，再检查 health.py 的路径配置。

### 步骤 8：启动服务

**执行位置：终端 A，复刻项目 backend。**

```bash
uv run uvicorn main:app --reload --host 127.0.0.1 --port 8100
```

`main:app` 的 main 对应 `backend/main.py`，冒号后的 app 对应该文件中的应用对象。文件夹 app 和变量 app 同名，但不是同一个对象；启动器先定位模块，再取对象。

终端中应出现包含 `Application startup complete` 和 `http://127.0.0.1:8100` 的日志。终端暂时不返回提示符是服务在等待请求；先保持它运行。

`--reload` 用于开发时监测源码变化并重新加载；重载会重新导入模块，不适合在模块顶层随意执行写数据库等有副作用的动作。

### 步骤 9：用新终端验证请求

**执行位置：新终端 B，任意目录。终端 A 保持运行。**

```bash
curl -i http://127.0.0.1:8100/health/live
```

预期 HTTP 状态码为 200，响应正文为：

```json
{"code":200,"message":"health application status","data":{"status":"ok"}}
```

再逐个执行：

```bash
curl -i http://127.0.0.1:8100/
curl -i http://127.0.0.1:8100/hello/Learner
curl -i http://127.0.0.1:8100/health
```

对应正文依次为：

```json
{"message":"Hello World"}
```

```json
{"message":"Hello Learner"}
```

```json
{"message":"The service is healthy"}
```

再验证一个不存在的地址：

```bash
curl -i http://127.0.0.1:8100/not-found
```

应返回 HTTP 404，正文为 `{"detail":"Not Found"}`。这是框架的默认响应，本篇尚未统一失败格式。

### 步骤 10：检查接口描述

在浏览器打开：

```text
http://127.0.0.1:8100/docs
```

可以看到当前接口；GET /health/live 会放在“健康检查”分组中。默认文档页面需要加载外部静态资源；若页面空白，先用下面的接口描述确认路由已生成：

```bash
curl -i http://127.0.0.1:8100/openapi.json
```

预期状态码 200，JSON 的 paths 内有 /health/live。接口返回正确与浏览器文档资源能否加载，要分别判断。

### 步骤 11：停止并重新启动

回到**终端 A**按 Control + C，等待关闭完成。需要继续开发时，在同一 backend 目录重新执行步骤 8 的启动命令。

这次不需要重新创建虚拟环境或重新安装依赖。当前没有写入业务数据，重启只会重新加载应用和路由。

## 6. 常见问题

| 现象 | 优先检查 | 处理 |
|---|---|---|
| Could not import module main | 当前目录和文件位置 | 确保在复刻 backend 执行，main.py 与 app 并列 |
| No module named app | app 目录、包标识及启动位置 | 核对三个 __init__.py 和导入路径，不改系统 PYTHONPATH 来绕过 |
| /health 正常但 /health/live 为 404 | 路由是否注册 | 核对 include_router、prefix 与 /live，并保存文件 |
| Address already in use | 8100 是否已有自己的服务 | 已有本篇服务就直接验证；否则找到占用者，不随意终止其他项目 |
| No module named fastapi | 当前解释器 | 在正确 backend 使用 uv run；必要时用 uv sync --locked 同步已有环境 |
| curl 连接失败 | 终端 A 的启动日志 | 确认服务未退出、地址与端口正确；这与 HTTP 404 不同 |
| /docs 空白但 openapi.json 正常 | 文档资源加载 | 查看浏览器网络情况，先用 curl 验证业务接口 |

## 7. 做完后核对

- [ ] 六个新增 Python 文件均在上面的复刻路径中。
- [ ] 服务可从复刻 backend 用 main:app 启动。
- [ ] /health/live 返回统一成功结构。
- [ ] /、/hello/Learner、/health 与预期一致。
- [ ] 不存在的路径返回 404，OpenAPI 包含当前路由。
- [ ] 能沿 main.py → health.py → success_response.py 找到调用关系。

本篇没有新增依赖，因此 requirements.txt、pyproject.toml 和 uv.lock 无需变化。可在复刻根目录用 `git status --short` 查看本次新增文件；本篇不要求清理或覆盖已有个人改动。

### 当前与原项目的差异

| 能力 | 本篇实现 | 继续补齐的位置 |
|---|---|---|
| 入口及基础接口 | 已给出与原项目对应的最小实现 | 后续路由逐步接入 |
| 成功响应 | 与参考字段结构一致 | 后续处理实际模型数据 |
| /health/live | 已实现 | 后续继续复用 |
| /health/ready | 尚未实现 | 数据库与 Redis 接入阶段 |
| 数据库、鉴权、笔记、图谱与模型 | 尚未实现 | 见[复刻路线](../roadmap.md) |

下一篇：[第 02 篇：请求模型、配置与统一错误处理](02-request-models-config-and-errors.md)。它会从当前文件继续，标记 main.py 的修改并建立真实落库前的数据与错误边界。

你实际提出的疑问继续记录到[知识问答册](../03-knowledge-q-and-a.md)；完成情况记到复刻项目自己的 项目学习记录，不因教程已提供就自动勾选。

### 本篇验证记录

**已执行接口验证（2026-10-20）**：从本文提取 6 个完整 Python 文件，在独立临时目录使用复刻项目的 Python 3.12.13 环境，实际启动 Uvicorn（含 --reload），监听 127.0.0.1:8100。

- 四个已列接口的 HTTP 200、JSON 正文和响应类型均通过。
- 不存在路径返回 404，错误请求方法返回 405。
- OpenAPI 包含当前路径及“健康检查”分组；/docs 返回 HTTP 200。
- 停止后重新启动，重复接口与描述检查通过，验证服务已停止。
- 文档页面未做浏览器渲染或点击验证；未连接数据库、模型或验证后续业务。

临时目录：`/tmp/verification-results.json`。以上为此前临时验证记录。随后已按用户要求在正式复刻目录创建本篇全部应用文件，执行教程中的 uv run 启动命令，并通过同样的接口、404/405、OpenAPI、文档 HTTP 和停止重启检查；正式服务现运行于 8100 端口。用户能力验收仍单独记录。
