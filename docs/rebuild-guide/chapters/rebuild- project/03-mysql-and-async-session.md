# 第 03 篇：接入 MySQL，建立异步数据库会话与生命周期

> 日期：2026-10-20。新版连续教程；面向有 Python、HTTP、JSON 与异步基础的读者。 
> 前置：完成[上一篇](02-request-models-config-and-errors.md)，从该篇最终文件继续。 
> 本篇成果：启动独立 MySQL，应用启动时检查连接，提供就绪检查，建立每个请求独立的会话。 
> 交付范围：本篇是操作教材，代码在独立临时目录验证；不会自动把新增代码写入你的正式复刻目录。

**技术路线原理与同类比较：** [Q04：Docker Compose 与本机安装](technology-routes/Q04-docker-compose-local-services.md) · [Q05：MySQL 与 PostgreSQL、SQLite](technology-routes/Q05-mysql-relational-database.md) · [Q06：SQLAlchemy 异步 ORM 与手写 SQL](technology-routes/Q06-sqlalchemy-async-orm.md)。

## 1. 本篇目标与操作起点

复刻根目录固定为：

```text
.
```

文中所有 backend/、app/ 等位置都以这里为准，不在上一级参考项目中写代码。用户当前正式项目只执行到新版第 01 篇；本篇及后续篇章需要按顺序完成，不能直接跳到最后一篇复制入口文件。

从第 02 篇继续。本篇增加 Docker Compose、数据库配置和生命周期，仍不创建 notes 表。所有数据库、数据卷和端口均属于复刻项目；原项目的 3306 端口和数据不参与本篇操作。

基础语法直接使用。本篇围绕正在创建的文件说明职责、数据与调用关系，重点解释新机制和为什么这样组织。
## 2. 文件与依赖变化

| 标记 | 文件 | 目的 |
|---|---|---|
| 【修改】 | 根 .env.example、本机 .env、app/core/settings.py | 声明 MySQL 地址、用户和数据库 |
| 【新增文件】 | 根 docker-compose.yml | 启动独立 MySQL 及其数据卷 |
| 【新增文件】 | app/db/__init__.py、db_config.py | 异步引擎、会话工厂、连接检查 |
| 【新增文件】 | app/core/lifespan.py | 把资源打开与关闭连接到应用生命周期 |
| 【修改】 | app/router/health.py | 加入 /health/ready |
| 【修改】 | backend/main.py | 把 lifespan 交给 FastAPI |
| 【工具生成】 | 依赖声明、锁文件和 requirements.txt | 加入 SQLAlchemy、异步驱动及认证支持 |

本篇使用真实 MySQL，不用内存字典模拟数据库。Docker Desktop 需要启动；只有 docker 命令可执行但服务未运行时，无法执行容器启动命令。

## 3. 按顺序准备数据库

**执行位置：复刻 backend。**
```bash
cd "./backend"
uv add "SQLAlchemy[asyncio]==2.0.48" "aiomysql==0.3.2" "cryptography==46.0.5" "PyMySQL==1.1.3"
uv export --locked --no-dev --no-emit-project --no-hashes --format requirements.txt --output-file requirements.txt
mkdir -p app/db
```
SQLAlchemy 负责 ORM 与数据库操作组织，aiomysql 负责 MySQL 的异步通信；asyncio 额外依赖会带入异步桥接所需的 greenlet，适合当前 Apple 芯片环境。cryptography 用于 MySQL 8 默认认证方式需要的 RSA 支持，避免把“缺认证依赖”误当作账户密码错误。PyMySQL 是 aiomysql 的底层依赖；这里固定 1.1.3，是因为当前 SQLAlchemy 2.0.48 与 PyMySQL 1.2.x 搭配时，连接池第二次取连接会触发 `ping()` 参数错误。固定兼容版本后继续使用 `pool_pre_ping=True`。SQLAlchemy 和 aiomysql 版本对照参考声明，认证支持版本对照参考锁文件。

先更新配置和 Compose，再启动数据库，最后替换生命周期与 main.py。应用入口更新后会真正检查数据库，不要在配置或容器尚未准备好时就判断启动失败是 Python 语法问题。
### 步骤 1：【修改】`backend/app/core/settings.py`

**编辑文件的完整地址：**

```text
./backend/app/core/settings.py
```

**修改定位与前后对照：** 根据下列函数名、配置项或导入位置定位；diff 仅供阅读，正负号不要复制进源码。对照以完成上一篇后的版本为准，请按 diff 修改已有文件。

```diff
--- backend/app/core/settings.py（修改前）
+++ backend/app/core/settings.py（修改后）
@@ -1,9 +1,9 @@
 from pathlib import Path
 from typing import Literal
 
+from pydantic import Field, SecretStr
 from pydantic_settings import BaseSettings, SettingsConfigDict
 
-# 【新增】从本文件定位复刻根目录，不受终端当前目录影响。
 REBUILD_ROOT = Path(__file__).resolve().parents[3]
 
 
@@ -17,5 +17,12 @@
     APP_NAME: str = "RAGNotebook Rebuild"
     ENV: Literal["dev", "test", "prod"] = "dev"
 
+    # 【新增 C01】这里是宿主机访问复刻 MySQL 的配置。
+    MYSQL_HOST: str = "127.0.0.1"
+    MYSQL_PORT: int = Field(default=13306, ge=1, le=65535)
+    MYSQL_USER: str = "rag_learner"
+    MYSQL_PASSWORD: SecretStr = SecretStr("mindweave_pass_change_me")
+    MYSQL_DATABASE: str = "MindWeave"
+
 
 settings = Settings()
```

**整体解释：** 新增配置为数据库画出一张地址卡：后端从 settings 取主机、端口和账户，再交给连接层。SecretStr 让密码在普通配置展示时被遮住；端口等校验提前发现填错的地址，避免请求来了才知道接不上 MySQL。新增数据库连接参数。MYSQL_PORT 是 Mac 上映射出来的 13306，后端目前是直接运行在 Mac 上的程序，所以连接 127.0.0.1:13306；容器内部 MySQL 仍监听 3306。SecretStr 在常规对象显示时会掩码，真正交给驱动时再显式提取。它不是加密文件，也不能保证任何自定义日志都不会泄漏；不要打印 .get_secret_value() 或整条连接 URL。配置默认值只服务本机开发。后续部署时明确提供实际值，不把这里的示例口令当作生产凭据。字段名与原项目 MYSQL_* 一致，独立端口和数据库名称是本机复刻环境的适配。

### 步骤 2：【修改】`.env.example`

**编辑文件的完整地址：**

```text
./.env.example
```

**修改定位与前后对照：** 根据下列函数名、配置项或导入位置定位；diff 仅供阅读，正负号不要复制进源码。对照以完成上一篇后的版本为准，请按 diff 修改已有文件。

```diff
--- .env.example（修改前）
+++ .env.example（修改后）
@@ -1,2 +1,8 @@
 APP_NAME=RAGNotebook Rebuild
 ENV=dev
+MYSQL_HOST=127.0.0.1
+MYSQL_PORT=13306
+MYSQL_USER=rag_learner
+MYSQL_PASSWORD=mindweave_pass_change_me
+MYSQL_DATABASE=MindWeave
+MYSQL_ROOT_PASSWORD=mindweave_root_change_me
```

**整体解释：** 示例环境文件列出了 MySQL 的接线编号；Compose 用本机 .env 创建数据库与应用账户，后端用同名配置连过去。root 密码用于容器初始化，应用平时用独立账号；两边字段必须对齐，像门牌和钥匙要指向同一扇门。APP_NAME、ENV 保留，后面新增 MYSQL_* 字段。MYSQL_ROOT_PASSWORD 仅供容器首次初始化管理账户；后端使用的是独立 rag_learner 用户，不使用 root。在编辑器打开复刻根目录现有 .env，保留已有值并补齐本例新增字段。本篇 .env.example 的示例可作为当前仅有基础配置时的完整对照；不要重新用 cp 覆盖已经填入的个人配置。如果你替换示例口令，要保持 .env 中 MYSQL_PASSWORD 与实际数据库用户口令一致。Compose 第一次创建数据目录时使用这些变量初始化用户和库。已有数据卷之后只改 .env 不会自动修改 MySQL 账户口令，后续排错时应检查已有卷，而不是反复删除数据来碰运气。

### 步骤 3：【新增文件】 `docker-compose.yml`

**编辑文件的完整地址：**

```text
./docker-compose.yml
```

**新建说明：** 先确认父目录已按本篇命令创建，再新建同名文件；整个文件都是本步新增内容。

**完整文件内容：**

<!-- file: docker-compose.yml -->
```yaml
name: MindWeave

services:
  mysql:
    image: mysql:8.0
    restart: unless-stopped
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD:?请在根目录.env中填写MYSQL_ROOT_PASSWORD}
      MYSQL_DATABASE: ${MYSQL_DATABASE:-MindWeave}
      MYSQL_USER: ${MYSQL_USER:-rag_learner}
      MYSQL_PASSWORD: ${MYSQL_PASSWORD:?请在根目录.env中填写MYSQL_PASSWORD}
    ports:
      - "127.0.0.1:${MYSQL_PORT:-13306}:3306"
    command:
      - --character-set-server=utf8mb4
      - --collation-server=utf8mb4_unicode_ci
      - --default-time-zone=+00:00
    volumes:
      - mysql_data:/var/lib/mysql
    healthcheck:
      test: ["CMD-SHELL", "mysqladmin ping -h 127.0.0.1 --silent"]
      interval: 5s
      timeout: 5s
      retries: 30
      start_period: 20s

volumes:
  mysql_data:
```

**文件作用：** 把镜像、初始化环境、端口和持久化存储写成可以重复运行的配置。逐项解释与 .env 的具体例子见[知识问答 Q005](../03-knowledge-q-and-a.md#q005)。

顶层 name 固定 Compose 项目名，因此容器和卷归入 MindWeave 这一组。这里不写与原项目重名的 container_name，也不借用原来的数据卷。

端口的左边是 Mac 上的 13306，右边是容器内 3306，绑定地址 127.0.0.1 限定本机访问。下一步的 Python 配置应填左边，不是因为“数据库默认 3306”就随手改回 3306。

`mysql_data` 保存 /var/lib/mysql，容器停止或重建不会自动丢掉数据。`docker compose down` 默认不删这个命名卷；本篇不执行 down -v。MySQL 的普通数据库初始化变量只在空数据目录时发挥作用。

utf8mb4 支持中文与常见表情。容器默认时区设为 UTC，后面时间字段统一按 UTC 存储；这不会让 MySQL 的 DateTime 自动带上 Python 时区对象。

healthcheck 的 mysqladmin ping 判断服务可响应，不替代后端应用账户的真实认证查询。真正确认 rag_learner 有权访问目标库，要看后端的 SELECT 1。

首次下载 mysql:8.0 需要网络；固定大版本系列方便学习环境适配，严格发布复现时再记录实际镜像 digest。

**执行位置：复刻根目录。先打开 Docker Desktop，等待服务运行。**
```bash
cd "."
docker version
docker compose config --quiet
docker compose up -d mysql
docker compose ps
docker compose logs --tail 60 mysql
```
预期 mysql 显示运行，等待初始化完成后显示 healthy。首次启动通常比后续重启慢；不要在正在初始化时频繁重建容器。`config --quiet` 只检查配置，不把环境值完整输出到聊天或日志。

如果 docker version 提示无法连接 daemon，先解决 Docker Desktop 服务；此时后续 Python 连接失败没有必要反复重装 SQLAlchemy。数据库就绪后继续创建文件。
### 步骤 4：【新增文件】 `backend/app/db/__init__.py`

**编辑文件的完整地址：**

```text
./backend/app/db/__init__.py
```

**新建说明：** 先确认父目录已按本篇命令创建，再新建同名文件；整个文件都是本步新增内容。

**完整文件内容：**

<!-- file: backend/app/db/__init__.py -->
```python
"""数据库连接与请求级会话依赖。"""
```

**作用：** 将连接基础设施集中到 db 包。以后业务服务从这里取得会话，不在每次操作时临时拼一套新的连接设置。

### 步骤 5：【新增文件】 `backend/app/db/db_config.py`

**编辑文件的完整地址：**

```text
./backend/app/db/db_config.py
```

**新建说明：** 先确认父目录已按本篇命令创建，再新建同名文件；整个文件都是本步新增内容。

**完整文件内容：**

<!-- file: backend/app/db/db_config.py -->
```python
from collections.abc import AsyncIterator

from sqlalchemy import URL, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.settings import settings

# 【新增】用结构化 URL 处理密码中的 @、: 等字符。
database_url = URL.create(
    drivername="mysql+aiomysql",
    username=settings.MYSQL_USER,
    password=settings.MYSQL_PASSWORD.get_secret_value(),
    host=settings.MYSQL_HOST,
    port=settings.MYSQL_PORT,
    database=settings.MYSQL_DATABASE,
    query={"charset": "utf8mb4"},
)

async_engine = create_async_engine(
    database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    # 【新增】每个请求拿独立会话；写入提交由服务层明确执行。
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def check_mysql_connection() -> bool:
    try:
        async with async_engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
```

**文件职责：** 引擎负责数据库连接池，会话工厂负责产生会话，get_db 将会话交给具体请求。逐段讲解与保存笔记的具体流程见[专项问答 Q007](../03-knowledge-q-and-a.md#q007)。三个对象有不同寿命，不能把同一个 AsyncSession 当全局对象供所有请求共用。

可以把连接池看作办公室共用的一组电话线路，Session 是某次办事过程的工作上下文。多个请求复用连接池，但各自处理自己的事务，不能让前一个人的未提交修改混进后一个人的请求。

URL.create 接收分开的用户名、口令和地址，避免手拼 URL 时密码含 @ 或冒号导致地址解析错误。这里不需要把口令打印出来排错。

create_async_engine 先创建管理对象，不代表创建对象的瞬间就已经连接成功；第一次 connect 或执行数据库操作才会真正取连接。pool_pre_ping 在借出池中连接前检查可用性，帮助发现过期连接；它不保证每次业务 SQL 永远不会失败。

expire_on_commit=False 让服务提交后还能读取已加载字段，减少异步代码中访问属性时发生隐式加载的问题。它不是全自动同步数据库：提交后需要数据库默认值时仍会显式 refresh。

get_db 中 yield 之前是准备会话，yield 出去的对象由路由/服务使用，请求结束后回到上下文关闭会话。异常时 rollback 后继续 raise，让上层处理错误。这里故意不在 yield 后自动 commit：后面写入服务在返回成功之前提交，避免已经开始返回成功才发现提交失败。

check_mysql_connection 做真实 SELECT 1，不读取用户数据。失败时对外只报告未就绪，具体连接阶段可通过容器日志和配置排查；不把完整连接串放进健康接口。

### 步骤 6：【新增文件】 `backend/app/core/lifespan.py`

**编辑文件的完整地址：**

```text
./backend/app/core/lifespan.py
```

**新建说明：** 先确认父目录已按本篇命令创建，再新建同名文件；整个文件都是本步新增内容。

**完整文件内容：**

<!-- file: backend/app/core/lifespan.py -->
```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.db.db_config import async_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        # 【新增】启动时先验证本项目账户可以连接目标数据库。
        async with async_engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        yield
    finally:
        # 【新增】启动失败或应用正常关闭时，都释放连接池资源。
        await async_engine.dispose()
```

**文件作用：** 把启动检查与关闭清理接到 FastAPI 的生命周期。

yield 前相当于开门前的检查，本篇要求数据库可连接后才正式接待请求；yield 后/ finally 负责关门后的资源归还。若启动数据库连接失败，应用启动失败，不会假装已经准备好。

finally 包住启动检查，因此即使检查抛错也会尝试释放已创建的引擎资源。它处理资源寿命，不等于给每个请求包一层异常处理器；HTTP 请求级错误由第 02 篇的机制处理。

参考项目使用启动/关闭事件函数，本篇采用 lifespan 组织同一类工作，便于将一对资源的创建和清理放在一起。这是结构组织方式的调整，不是额外启动一个后台服务。

### 步骤 7：【修改】`backend/app/router/health.py`

**编辑文件的完整地址：**

```text
./backend/app/router/health.py
```

**修改定位与前后对照：** 根据下列函数名、配置项或导入位置定位；diff 仅供阅读，正负号不要复制进源码。对照以完成上一篇后的版本为准，请按 diff 修改已有文件。

```diff
--- backend/app/router/health.py（修改前）
+++ backend/app/router/health.py（修改后）
@@ -1,16 +1,26 @@
-from fastapi import APIRouter
+from fastapi import APIRouter, HTTPException
 from fastapi.responses import JSONResponse
 
 from app.core.success_response import success_response
+from app.db.db_config import check_mysql_connection
 
-# 【新增】这个路由组内的路径统一以 /health 开头。
 health_router = APIRouter(prefix="/health")
 
 
 @health_router.get("/live", tags=["健康检查"], summary="健康检查")
 async def get_health_application_status() -> JSONResponse:
-    # 【新增】交给公共工具构造与参考项目一致的成功响应。
     return success_response(
         message="health application status",
         data={"status": "ok"},
     )
+
+
+@health_router.get("/ready", tags=["健康检查"], summary="数据库就绪检查")
+async def get_health_readiness() -> JSONResponse:
+    # 【新增 C01】能接请求与能连接业务依赖，是两种不同状态。
+    if not await check_mysql_connection():
+        raise HTTPException(status_code=503, detail="MySQL连接失败")
+    return success_response(
+        message="health readiness status",
+        data={"status": "ok"},
+    )
```

**整体解释：** 健康检查分成两道门：/live 确认后端还会回答，/ready 则真正访问 MySQL 并执行 SELECT 1。数据库断开时进程可能还活着，但已经办不了笔记业务，因此就绪接口用 503 提醒调用方暂缓送来依赖数据库的请求。新增连接检查导入和 /ready，原 /live 的响应继续保留。/live 像前台能否接电话，/ready 像接待以后是否能办理当前数据库业务。MySQL 停止时，已经运行的应用仍可能回答 /live，但 /ready 应返回 503。若一开始数据库就没启动，本篇启动前检查会阻止应用启动，此时两个地址都不能访问。503 来自 HTTPException，经第 02 篇注册的处理器包装为 code=503、message=MySQL连接失败、data=null。参考原 /ready 还检查 Redis；当前尚未接入 Redis，所以明确只检查 MySQL，在 Redis 阶段扩展，不能把本篇 ready 说成全系统就绪。健康检查失败返回 bool 不意味着业务查询也要吞异常。后面服务层仍让真实写入失败向上抛出，不能发生写入失败却返回成功。

### 步骤 8：【修改】`backend/main.py`

**编辑文件的完整地址：**

```text
./backend/main.py
```

**修改定位与前后对照：** 根据下列函数名、配置项或导入位置定位；diff 仅供阅读，正负号不要复制进源码。对照以完成上一篇后的版本为准，请按 diff 修改已有文件。

```diff
--- backend/main.py（修改前）
+++ backend/main.py（修改后）
@@ -1,14 +1,14 @@
 from fastapi import FastAPI
 
 from app.core.failed_response_register import register_exception_handlers
+from app.core.lifespan import lifespan
 from app.core.settings import settings
 from app.router.health import health_router
 
-# 【修改 C01】应用元信息来自统一配置入口。
-app = FastAPI(title=settings.APP_NAME)
+# 【修改 C01】应用启动检查和关闭清理由 lifespan 管理。
+app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
 
 app.include_router(health_router)
-# 【新增 C02】让自定义错误处理器真正进入应用。
 register_exception_handlers(app)
```

**整体解释：** lifespan 是应用的值班交接表：FastAPI 启动时先进入它，完成依赖检查和准备，关停时再走清理流程。main.py 传入这个函数后，前面写好的数据库准备逻辑才会在接待请求之前执行。新增 lifespan 导入，FastAPI 构造器多传 lifespan=lifespan；路由与异常注册保持原样。参数与 yield 前后的具体解释见[专项问答 Q008](../03-knowledge-q-and-a.md#q008)。这里传入的是生命周期函数，不是提前执行它。Uvicorn 启动应用时由框架进入该上下文，关闭应用时退出。同样是“先交给框架，等合适时机调用”，但它与 include_router 管理的是不同规则。不要把创建数据库引擎、启动服务、处理请求混在一起：模块导入产生对象，生命周期检查资源，请求阶段才做具体查询。

## 4. 连接、请求与关闭的完整过程

启动阶段：Settings 读根 .env → db_config 创建引擎与会话工厂 → FastAPI 挂载 lifespan → 连接池取得 MySQL 连接 → SELECT 1 成功 → 进入可服务状态。

请求阶段：/ready 调用连接检查，单次查询完成后归还连接。未来笔记接口由 Depends(get_db) 拿独立 Session，不会直接使用健康检查函数代替业务查询。

关闭阶段：停止 Uvicorn → 退出 lifespan → dispose 释放连接池。MySQL 容器没有因此被停止，命名卷也没有因此删除。Python 进程、容器和持久化数据是三个不同层次。

## 5. 实际运行与数据库检查

**先在复刻根目录启动容器，再在 backend 启动应用。**
```bash
cd "./backend"
uv run uvicorn main:app --reload --host 127.0.0.1 --port 8100
```
```bash
curl -i http://127.0.0.1:8100/health/live
curl -i http://127.0.0.1:8100/health/ready
```
正常情况下两个接口都返回 HTTP 200；/ready 表示本篇的 MySQL 应用账户能完成查询。

**直接检查库是否创建。执行位置：复刻根目录。**
```bash
cd "."
docker compose exec mysql sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" exec mysql -u "$MYSQL_USER" "$MYSQL_DATABASE"'
```
命令会在容器内部读取已有的 `MYSQL_PASSWORD`，自动交给 MySQL 客户端；无需手动输入密码。外层单引号让变量在容器内展开，终端不会打印密码。进入 MySQL 后执行：
```sql
SELECT DATABASE();
SELECT 1;
SHOW TABLES;
exit;
```
本篇 SHOW TABLES 为空可以是正常结果：数据库已创建，但还没有注册笔记模型。连接成功和表结构已经创建是两件事。

**可选的依赖断开验证：** 只针对复刻项目，在根目录执行 `docker compose stop mysql`，等连接检查超时后 /ready 应为 503；随后 `docker compose start mysql`，等待健康后重新请求应恢复。本篇不执行删除卷命令。若把 Python 服务也停掉，就无法用 /live 对比两个状态。

## 6. 常见问题

| 现象 | 具体定位 | 处理 |
|---|---|---|
| Cannot connect to Docker daemon | docker version 的 Server 段 | 启动 Docker Desktop 后再操作 |
| Connection refused | Compose 状态、端口与初始化日志 | 等待 MySQL 就绪，确认宿主机使用 13306 |
| Access denied | 用户、密码与已有数据卷 | 核对应用账户，已有卷不会跟随 .env 自动改密码 |
| Unknown database | 首次初始化环境与已有卷 | 检查数据库是否真的创建，勿直接删卷 |
| greenlet 相关错误 | SQLAlchemy 安装方式 | 使用本篇的 SQLAlchemy[asyncio] 声明并同步环境 |
| cryptography is required | MySQL 8 认证路径 | 核对认证依赖已装进当前 .venv |
| app启动失败，/live也不能访问 | 终端启动 traceback | 本篇在启动时检查数据库，先修复连接再重启 |

## 7. 完成状态与后续衔接

- [ ] Compose 项目名和 13306 端口独立。
- [ ] 根 .env 与 Settings、Compose 的数据库配置一致。
- [ ] /live 和 /ready 的含义能够对应实际行为。
- [ ] 应用停止时释放连接池，容器数据继续保留。
- [ ] requirements.txt 与新增依赖同步，真实 .env 未进入 Git。

下一篇[建立笔记表与创建读取接口](04-note-model-and-create-read.md)会在本篇基础上增加 Base、Note、init_db 和服务层，第一次真正向数据库写入笔记。不要提前在其他位置写另一套全局 Session。

**参考源码：** [数据库连接](../../../backend/app/db/db_config.py)、[健康检查](../../../backend/app/router/health.py)、[原应用入口](../../../backend/main.py)。本篇将事务提交交给后续服务显式控制，与参考 get_db 在 yield 后统一提交的做法不同，原因是希望成功响应前就知道写入是否完成。

### 本篇验证记录

**已执行部分验证（2026-10-20）**：SQLAlchemy[asyncio] 2.0.48、aiomysql 0.3.2 与 cryptography 46.0.5 在临时环境安装成功；docker compose config --quiet 通过；异步引擎、生命周期与 /ready 在临时 SQLite 替代连接下通过。

**尚未执行**：当前 Docker daemon 不可连接，因此没有启动 MySQL 容器，没有验证 MySQL 认证、13306 连接、真实账户权限、镜像启动或卷持久化。SQLite 检查不能证明这些能力；请按本篇在 Docker 运行后完成验证。没有改动你的原项目容器或正式复刻环境。

本轮临时验证记录：`/tmp/verification-results.json`。所有验证服务均已停止；正式 8100 服务及其源码不参与本轮变更。

**后续本机验证更新（2026-10-20）：** 已按用户报错修复 Docker Desktop 未启动及 .env 缺失，实际启动复刻 MySQL 8.0.46，容器 healthy；应用账户通过 127.0.0.1:13306 连接目标库并执行 SELECT 1 成功。上述 SQLite 测试为先前记录，此更新补上容器初始化、认证与宿主机连接实测；本篇 ORM 生命周期与后续 CRUD 尚未在正式项目完整执行。排错见 [Q006](../03-knowledge-q-and-a.md#q006)。
