# 第 22 篇：知识库文档表、切片表和列表

> 前置：第 21 篇完成后的后端状态。本篇已代执行到正式复刻目录。
> 成果：给知识库建立真实 MySQL 结构，接通 `GET /knowledge/list`，使复制来的知识库页面至少能读取当前用户的文档列表。
> 验证标记：正式 MySQL 已创建两张知识表；`GET /knowledge/list` 已通过真实请求、账号隔离及上传后可见性检查。

## 1. 本篇目标与对齐边界

给知识库建立真实 MySQL 结构，接通 `GET /knowledge/list`，使复制来的知识库页面至少能读取当前用户的文档列表。

参考项目的知识库最终还有 PDF、向量、图片和图谱。本篇先建立持久化文档与切片的骨架，不把空列表称为完整知识库。

本篇只动后端。原项目的前端已经直接复制到复刻目录；你无需新建或修改前端文件。后端讲解沿真实的 `router → schema → service → model/数据库` 关系进行，不重复已掌握的 Python 基础语法。

## 2. 目录与文件变化

本篇沿用现有 `backend/app` 目录；只有下表标为【新增文件】的路径需要新建。修改已有文件时，diff 仅显示本篇变化，`+`、`-` 不能复制进源码。

| 标记 | 文件 | 职责 |
|---|---|---|
| 【新增文件】 | `backend/app/models/knowledge_document.py` | MySQL 表结构 |
| 【修改】 | `backend/app/db/db_config.py` | 建表模型注册 |
| 【修改】 | `backend/app/schemas/models.py` | 请求/响应字段与校验 |
| 【新增文件】 | `backend/app/services/knowledge_service.py` | 用户范围内的业务与事务 |
| 【新增文件】 | `backend/app/router/knowledge_router.py` | HTTP 路径、依赖和响应 |
| 【修改】 | `backend/main.py` | 路由组装配 |

## 3. 按顺序操作

终端执行位置：

```text
.
```

```bash
cd "."
```

本篇验证沿用第 17 篇取得的 `RAG_TOKEN`。如果换了终端，请先按[第 17 篇第 3 节](17-note-category-stats.md#3-按顺序操作)重新取得令牌；不要把密码或令牌写入 Markdown。

### 步骤 1：【新增文件】 `backend/app/models/knowledge_document.py`

**编辑文件的完整地址：**

```text
./backend/app/models/knowledge_document.py
```

**文件职责与完整内容：** 先确认父目录已存在；本篇创建的是这个新文件，下面代码可整体保存。

```python
"""知识文档及其切片在 MySQL 中的结构。"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.mysql import LONGTEXT

from app.models.base import Base


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("user_id", "filename", name="uq_knowledge_user_filename"),
        UniqueConstraint("user_id", "md5", name="uq_knowledge_user_md5"),
    )

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), index=True, nullable=False)
    filename = Column(String(255), nullable=False)
    md5 = Column(String(32), nullable=False)
    file_size = Column(Integer, nullable=False)
    content = Column(LONGTEXT, nullable=False)
    status = Column(String(20), default="completed", nullable=False)
    chunk_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(), server_default=func.now(), nullable=False)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id = Column(String(36), primary_key=True)
    document_id = Column(
        String(36), ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    page = Column(Integer, nullable=True)
    images = Column(JSON, default=list, nullable=False)
```

**整体解释：** 一份文档像一本书，一条切片像书中的一页索引卡。`knowledge_documents` 保存归属、文件名、内容摘要所需的全文、MD5 和切片数量；`knowledge_chunks` 用 `document_id` 指回这本书。两个用户可以上传同名文件，但同一用户的同名或同内容文件由唯一约束挡住。正文用 MySQL `LONGTEXT`，因为后续允许的文本大于普通 `TEXT` 的容量；这里明确依赖 MySQL，不宣称能直接换 SQLite。切片表的外键为日后删除提供数据库层保护。

### 步骤 2：【修改】 `backend/app/db/db_config.py`

**编辑文件的完整地址：**

```text
./backend/app/db/db_config.py
```

**修改定位与前后对照：** 按 diff 的上下文定位已有函数或导入位置；本篇不重复展示整份修改后文件。

```diff
--- backend/app/db/db_config.py（修改前）
+++ backend/app/db/db_config.py（修改后）
@@ -56,6 +56,7 @@
     from app.models.note import Note  # noqa: F401
     from app.models.user_model import User  # noqa: F401
     from app.models.note_template import NoteTemplate  # noqa: F401
+    from app.models.knowledge_document import KnowledgeDocument, KnowledgeChunk  # noqa: F401
 
     async with async_engine.begin() as connection:
         await connection.run_sync(Base.metadata.create_all)
```

**整体解释：** 模型类必须在 `init_db()` 执行 `Base.metadata.create_all` 前被导入，SQLAlchemy 才知道还有两张知识表。可以把 `Base.metadata` 看成待检查的建表清单：只导入 Python 文件但不登记到清单，启动时就不会建表。`create_all` 只会创建缺失表，不负责以后修改已有列；未来结构变更要用迁移。

### 步骤 3：【修改】 `backend/app/schemas/models.py`

**编辑文件的完整地址：**

```text
./backend/app/schemas/models.py
```

**修改定位与前后对照：** 按 diff 的上下文定位已有函数或导入位置；本篇不重复展示整份修改后文件。

```diff
--- backend/app/schemas/models.py（修改前）
+++ backend/app/schemas/models.py（修改后）
@@ -111,3 +111,23 @@
 
 class BatchCategoryRequest(BatchIdsRequest):
     category: str = Field(max_length=50)
+
+
+class KnowledgeDocumentResponse(BaseModel):
+    model_config = ConfigDict(from_attributes=True)
+
+    id: str
+    filename: str
+    user_id: str
+    md5: str
+    file_size: int
+    file_type: str = ""
+    status: str
+    chunk_count: int
+    preview: str = ""
+    created_at: datetime
+
+
+class KnowledgeListResponse(BaseModel):
+    documents: list[KnowledgeDocumentResponse]
+    total_count: int
```

**整体解释：** 响应模型定义给浏览器看的字段，而不是直接把 ORM 行和连接细节丢给页面。列表响应保持参考前端识别的 `documents` 与 `total_count`；单条响应包含 `id`、`filename`、`file_type`、`chunk_count`、`created_at` 等。`file_type` 在这阶段是文件名末尾的类型标记（`txt` 或 `md`），由服务补上；`preview` 也由服务从正文截取，避免列表一次传回每份文档的全部内容。

### 步骤 4：【新增文件】 `backend/app/services/knowledge_service.py`

**编辑文件的完整地址：**

```text
./backend/app/services/knowledge_service.py
```

**文件职责与完整内容：** 先确认父目录已存在；本篇创建的是这个新文件，下面代码可整体保存。

```python
"""知识文档的用户范围查询与后续导入服务。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_document import KnowledgeDocument
from app.schemas.models import KnowledgeDocumentResponse, KnowledgeListResponse


class KnowledgeService:
    async def list_documents(
        self, db: AsyncSession, user_id: str
    ) -> KnowledgeListResponse:
        result = await db.execute(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.user_id == user_id)
            .order_by(KnowledgeDocument.created_at.desc(), KnowledgeDocument.id.desc())
        )
        documents = [
            KnowledgeDocumentResponse.model_validate(document).model_copy(
                update={
                    "file_type": document.filename.rsplit(".", 1)[-1].lower(),
                    "preview": document.content[:120],
                }
            )
            for document in result.scalars().all()
        ]
        return KnowledgeListResponse(documents=documents, total_count=len(documents))


knowledge_service = KnowledgeService()
```

**整体解释：** 列表服务先按 `KnowledgeDocument.user_id` 过滤，再按创建时间倒序取记录。每条 ORM 对象转成响应模型，`preview` 只取前 120 个字符；现在没有上传接口，第一次请求通常是空数组和 0。这里的空是数据库查询的真实结果，不是前端硬编码示例。

### 步骤 5：【新增文件】 `backend/app/router/knowledge_router.py`

**编辑文件的完整地址：**

```text
./backend/app/router/knowledge_router.py
```

**文件职责与完整内容：** 先确认父目录已存在；本篇创建的是这个新文件，下面代码可整体保存。

```python
"""知识库 HTTP 接口。"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.success_response import success_response
from app.db.db_config import get_db
from app.services.knowledge_service import knowledge_service
from app.utils.auth_utils import get_current_user_id

knowledge_router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@knowledge_router.get("/list")
async def list_documents(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    data = await knowledge_service.list_documents(db, user_id)
    return success_response(data=data)
```

**整体解释：** `/knowledge/list` 先通过 JWT 得到当前用户，再把请求级数据库会话交给服务。接口保持 `{code,message,data}` 外层结构，原前端 `knowledgeApi.list()` 已经按这个路径请求，无需再改页面源码。

### 步骤 6：【修改】 `backend/main.py`

**编辑文件的完整地址：**

```text
./backend/main.py
```

**修改定位与前后对照：** 按 diff 的上下文定位已有函数或导入位置；本篇不重复展示整份修改后文件。

```diff
--- backend/main.py（修改前）
+++ backend/main.py（修改后）
@@ -4,6 +4,7 @@
 from app.core.lifespan import lifespan
 from app.core.settings import settings
 from app.router.health import health_router
+from app.router.knowledge_router import knowledge_router
 from app.router.note_router import note_router
 from app.router.note_template_router import note_template_router
 from app.router.user import user_router
@@ -12,6 +13,7 @@
 app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
 
 app.include_router(health_router)
+app.include_router(knowledge_router)
 # 【新增 C01】把笔记接口组注册到同一个应用。
 app.include_router(note_router)
 # 【新增 C01】注册用户相关接口。
```

**整体解释：** 主应用登记新的知识路由组。单独创建 `knowledge_router.py` 不会让 FastAPI 自动发现它；`app.include_router(knowledge_router)` 才把地址加入总路由表。导入与登记发生在启动装配阶段，真正查询要等请求到来。

## 4. 这些文件怎样连成一次请求

启动后端 → `lifespan` 调 `init_db()` → 两个 ORM 模型进入 `Base.metadata`，MySQL 创建缺失表。打开知识库页 → 前端请求 `/knowledge/list` → 用户令牌限定查询范围 → 返回该用户的文档列表；本篇未上传时是空列表。

## 5. 运行与验证

先完成上述文件操作；若后端尚未运行，在复刻 `backend` 执行 `uv run uvicorn main:app --reload --host 127.0.0.1 --port 8100`，另开终端执行下列命令。命令中的 `RAG_TOKEN` 是第 3 节取得的本机变量。

```bash
curl -sS http://127.0.0.1:8100/knowledge/list -H "Authorization: Bearer $RAG_TOKEN" | python3 -m json.tool
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8100/knowledge/list
```

**预期观察：** 改完 `init_db` 和 `main.py` 后**重启后端**触发建表。带令牌请求应返回 `data.documents: []`、`data.total_count: 0`；无令牌返回 401。若启动报表不存在，先检查 `init_db` 导入和数据库连接，不要把空列表写成模拟数据。

**排查顺序：** 先看后端终端是否成功启动，再看 URL 与方法、Bearer 令牌、请求字段和响应的 HTTP 状态及 `code`。`401` 先查登录/Redis；`422` 先查路径或请求模型；业务 `code` 非 200 先读 `message`；MySQL 异常再查数据库连接和表结构。不要在未确认错误位置时修改前端。

## 6. 本篇边界与下一篇

本篇只建表和列表；文档正文与切片将从第 23–24 篇开始产生。并发或结构变更需后续迁移设计。

第 23 篇先把 TXT/Markdown 字节变成可存储的纯文本与切片。
