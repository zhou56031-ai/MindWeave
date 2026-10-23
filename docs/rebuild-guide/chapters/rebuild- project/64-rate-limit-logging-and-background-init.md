# 第 64 篇：限流、请求日志与后台预热

## 1. 本篇要接通的真实能力

参考项目在聊天、上传和重排接口上有 Redis 限流，并记录请求耗时、模型耗时和 token 使用。复刻项目功能能运行，但缺少这层治理。本篇增加可开关的 Redis 限流、`X-Process-Time`、结构化请求日志和向量模型预热。技术路线见 [Q15](technology-routes/Q15-deepseek-model-client.md) 与 [Q21](technology-routes/Q21-persistent-work-queues.md)。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 文件 | 职责 |
|---:|---|---|---|
| 1 | 【修改】 | backend/app/core/settings.py、.env.example、docker-compose.yml | 限流、日志和容器环境配置 |
| 2 | 【新增文件】 | backend/app/core/rate_limit.py | Redis 固定窗口计数 |
| 3 | 【新增文件】 | backend/app/core/observability.py | 请求耗时与日志中间件 |
| 4 | 【修改】 | backend/main.py | 注册中间件 |
| 5 | 【修改】 | backend/app/router/chat_router.py、knowledge_router.py | 关键接口限流 |
| 6 | 【新增文件】 | backend/app/core/warmup.py | Embedding 预热 |
| 7 | 【修改】 | backend/app/core/lifespan.py | 启动后台预热 |
| 8 | 【运行验证】 | 429、耗时头和冷启动 | 验证开关与降级 |

## 3. 按顺序修改文件与验证

### 步骤 1：【修改】backend/app/core/settings.py 与 .env.example

**编辑文件的完整地址：**

~~~text
./backend/app/core/settings.py
~~~

~~~diff
     WEB_SEARCH_API_KEY: SecretStr = SecretStr("")
+
+    RATE_LIMIT_ENABLED: bool = True
+    RATE_LIMIT_CHAT_PER_MINUTE: int = Field(default=10, ge=1, le=1000)
+    RATE_LIMIT_UPLOAD_PER_MINUTE: int = Field(default=5, ge=1, le=1000)
+    LOG_LEVEL: str = "INFO"
~~~

**编辑文件的完整地址：**

~~~text
./.env.example
~~~

~~~diff
 WEB_SEARCH_API_KEY=
+RATE_LIMIT_ENABLED=true
+RATE_LIMIT_CHAT_PER_MINUTE=10
+RATE_LIMIT_UPLOAD_PER_MINUTE=5
+LOG_LEVEL=INFO
~~~

Compose 的 backend/worker 共享环境也要显式传入这些键，否则根目录 `.env` 中的自定义值不会自动进入容器：

~~~diff
       WEB_SEARCH_API_KEY: ${WEB_SEARCH_API_KEY:-}
+      RATE_LIMIT_ENABLED: ${RATE_LIMIT_ENABLED:-true}
+      RATE_LIMIT_CHAT_PER_MINUTE: ${RATE_LIMIT_CHAT_PER_MINUTE:-10}
+      RATE_LIMIT_UPLOAD_PER_MINUTE: ${RATE_LIMIT_UPLOAD_PER_MINUTE:-5}
+      LOG_LEVEL: ${LOG_LEVEL:-INFO}
~~~

**整体解释：** 限流参数进入 Settings，测试可以把它关闭，生产可以按网关和用户量调整。日志级别同样由环境控制，不在代码中散落 `print`。Compose 显式映射保证宿主机 `.env`、容器运行时和后端 Pydantic 读取到同一组值。

### 步骤 2：【新增文件】backend/app/core/rate_limit.py

**编辑文件的完整地址：**

~~~text
./backend/app/core/rate_limit.py
~~~

**完整文件内容：**

~~~python
"""基于 Redis 固定窗口的请求限流。"""
import time
from collections.abc import Awaitable, Callable
from ipaddress import ip_address

from fastapi import HTTPException, Request

from app.core.settings import settings
from app.db.redis_config import get_redis


def _client_address(request: Request) -> str:
    # Compose 的 Nginx 会覆盖 X-Real-IP；后端端口只绑定宿主机回环地址。
    forwarded = request.headers.get("x-real-ip")
    if forwarded:
        try:
            return str(ip_address(forwarded.strip()))
        except ValueError:
            pass
    return request.client.host if request.client else "unknown"


def rate_limit(
    scope: str,
    limit: int,
    window_seconds: int = 60,
) -> Callable[[Request], Awaitable[None]]:
    window = max(1, int(window_seconds))

    async def dependency(request: Request) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        client = _client_address(request)
        window_number = int(time.time()) // window
        key = f"rate_limit:{scope}:{client}:{window_number}"
        try:
            redis = get_redis()
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, window + 1)
            if count > limit:
                raise HTTPException(
                    status_code=429,
                    detail="请求过于频繁，请稍后再试",
                    headers={"Retry-After": str(window)},
                )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="限流服务暂不可用",
            ) from exc
    return dependency
~~~

**整体解释：** 固定窗口实现简单，极端边界可能允许跨窗口突发；优点是容易理解、测试和观察。容器部署时后端看到的直连地址是 Nginx 容器 IP，因此优先读取代理写入的 `X-Real-IP`，并用 `ipaddress` 拒绝非法值；后端端口只绑定宿主机回环地址，避免外部绕过代理伪造头。Redis 故障时限流明确 503，而不是静默放行或让业务一直等待；高可用场景可以改成令牌桶并设置降级策略。

### 步骤 3：【新增文件】backend/app/core/observability.py

**编辑文件的完整地址：**

~~~text
./backend/app/core/observability.py
~~~

**完整文件内容：**

~~~python
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
            request.method, request.url.path, elapsed,
        )
        raise

    elapsed = (time.perf_counter() - started) * 1000
    response.headers["X-Process-Time"] = f"{elapsed / 1000:.4f}"
    logger.info(
        "request_completed method=%s path=%s status=%s duration_ms=%.1f",
        request.method, request.url.path, response.status_code, elapsed,
    )
    return response
~~~

**整体解释：** 中间件包住每个请求，返回前写入耗时头并记录一条结构化日志。日志不记录 Authorization、请求正文和查询参数，避免 token 与私人笔记进入日志。

### 步骤 4：【修改】backend/main.py

**编辑文件的完整地址：**

~~~text
./backend/main.py
~~~

~~~diff
+from app.core.observability import configure_logging, process_time_middleware
@@
 configure_logging()
 app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
+app.middleware("http")(process_time_middleware)
~~~

**整体解释：** 中间件注册在路由之前，但真正执行时按请求包住路由。健康检查也会被记录；如果日志量太大，应在生产采样或只记录错误和慢请求。

### 步骤 5：【修改】backend/app/router/chat_router.py 与 knowledge_router.py

**编辑文件的完整地址：**

~~~text
./backend/app/router/chat_router.py
~~~

~~~diff
+from app.core.rate_limit import rate_limit
+from app.core.settings import settings
@@
 chat_router = APIRouter(prefix="/chat", tags=["chat"])
+chat_rate_limit = rate_limit("chat", settings.RATE_LIMIT_CHAT_PER_MINUTE)
@@
 async def query_stream(
     payload: ChatQueryRequest,
     user_id: str = Depends(get_current_user_id),
     db: AsyncSession = Depends(get_db),
+    _: None = Depends(chat_rate_limit),
 ) -> StreamingResponse:
~~~

**编辑文件的完整地址：**

~~~text
./backend/app/router/knowledge_router.py
~~~

~~~diff
+from app.core.rate_limit import rate_limit
+from app.core.settings import settings
@@
 knowledge_router = APIRouter(prefix="/knowledge", tags=["knowledge"])
+upload_rate_limit = rate_limit(
+    "upload",
+    settings.RATE_LIMIT_UPLOAD_PER_MINUTE,
+)
@@
 async def add_single_document(
     file: UploadFile = File(...),
     user_id: str = Depends(get_current_user_id),
     db: AsyncSession = Depends(get_db),
+    _: None = Depends(upload_rate_limit),
 ) -> JSONResponse:
~~~

**整体解释：** 路由依赖在进入业务函数前执行，超限请求不会读文件、调用模型或开启事务。聊天和上传分别使用不同 scope，避免上传次数吃掉聊天额度。复刻代码把同一聊天依赖也用于审批恢复与重排，把同一上传依赖用于单文件、多文件、SSE 多文件入口；三者共享额度是因为它们代表同一类昂贵操作。`Retry-After` 告诉客户端至少等待一个窗口，Redis 自身故障则返回 503。

### 步骤 6：【新增文件】backend/app/core/warmup.py

**编辑文件的完整地址：**

~~~text
./backend/app/core/warmup.py
~~~

**完整文件内容：**

~~~python
"""在后台预热本地 Embedding，缩短首个检索请求。"""
import asyncio
import logging

from app.rag.embedding import embed

logger = logging.getLogger("mindweave.warmup")


async def warm_embedding() -> None:
    logger.info("embedding_warmup_started")
    try:
        await embed("预热")
    except Exception:
        logger.warning("embedding_warmup_failed", exc_info=True)
        return
    logger.info("embedding_warmup_completed")


def start_warmup() -> asyncio.Task:
    return asyncio.create_task(warm_embedding(), name="embedding-warmup")
~~~

**整体解释：** 预热失败不应阻止 API 启动；模型未下载或内存不足时仍保持可用，只是首个请求更慢。任务在事件循环里运行，不阻塞 lifespan 的数据库检查。

### 步骤 7：【修改】backend/app/core/lifespan.py

**编辑文件的完整地址：**

~~~text
./backend/app/core/lifespan.py
~~~

~~~diff
+import asyncio
+from contextlib import suppress
+from app.core.warmup import start_warmup
@@
 async def lifespan(app: FastAPI):
+    warmup_task: asyncio.Task | None = None
     try:
         await init_db()
+        warmup_task = start_warmup()
         yield
     finally:
+        if warmup_task is not None and not warmup_task.done():
+            warmup_task.cancel()
+            with suppress(asyncio.CancelledError):
+                await warmup_task
         await close_graph_driver()
~~~

**整体解释：** 数据库建表完成后启动轻量预热，应用开始接请求；关闭时取消未完成任务并等待取消完成，避免事件循环关闭后任务仍在收尾。预热失败只记 warning，不阻塞启动。它只预热 Embedding，不预热远程 DeepSeek，因为模型 API 的健康检查会产生额外费用。

### 步骤 8：【运行验证】429、耗时头和冷启动

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv run python -m compileall -q app main.py
~~~

把聊天限流设为 2 次/分钟，连续请求三次，第三次应为 429。检查响应头包含 `X-Process-Time`，日志不包含 Authorization。把 `RATE_LIMIT_ENABLED=false` 后同一请求不再 429。清空 Hugging Face 模型缓存后启动后端，观察预热日志；模型下载失败时 health/ready 仍应返回 200，但聊天检索可能先失败并回退 MySQL。

**本次实际验证：** 真实 Redis 使用独立 scope 连续调用 3 次、限制设为 2，结果为 `ok / ok / 429`，键 TTL 为 61 秒，验证后已删除测试键。自动测试覆盖关闭限流不访问 Redis、Redis 异常返回 503、代理客户端 IP、健康接口带 `X-Process-Time`，以及 Embedding 预热失败不影响调用方。实际启动 FastAPI 后，Embedding 从本机缓存加载成功，日志依次出现 `embedding_warmup_started` 和 `embedding_warmup_completed`；关闭应用时 lifespan 正常退出。访问日志只格式化方法、路径、状态和耗时，不读取 Authorization 或请求正文。没有清空模型缓存来强制重新下载，以避免重复消耗网络与磁盘。

