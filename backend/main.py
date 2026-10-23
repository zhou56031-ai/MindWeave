from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.failed_response_register import register_exception_handlers
from app.core.lifespan import lifespan
from app.core.observability import configure_logging, process_time_middleware
from app.core.settings import REBUILD_ROOT, settings
from app.graph.router import graph_router
from app.router.file_router import file_router
from app.router.health import health_router
from app.router.knowledge_router import knowledge_router
from app.router.note_router import note_router
from app.router.note_template_router import note_template_router
from app.router.review_router import review_router
from app.router.chat_router import chat_router
from app.router.user import user_router

configure_logging()

# 【修改 C01】应用启动检查和关闭清理由 lifespan 管理。
app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
app.middleware("http")(process_time_middleware)

app.include_router(health_router)
# 【新增 C01】把笔记接口组注册到同一个应用。
app.include_router(note_router)
# 【新增 C01】注册用户相关接口。
app.include_router(user_router)
# 【新增 C01】注册笔记模板接口。
app.include_router(note_template_router)
app.include_router(review_router)
app.include_router(chat_router)
app.include_router(knowledge_router)
app.include_router(graph_router)
app.include_router(file_router)
media_root = REBUILD_ROOT / "media"
media_root.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=media_root), name="media")
register_exception_handlers(app)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Hello World"}


@app.get("/hello/{name}")
async def say_hello(name: str) -> dict[str, str]:
    return {"message": f"Hello {name}"}


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"message": "The service is healthy"}
