# 第 26 篇：知识文档详情、切片、MD5 与删除

> 前置：第 25 篇完成后的后端状态。本篇已代执行到正式复刻目录。
> 成果：接通知识库页面剩余的详情、切片、按文件名删除、按 MD5 删除和清空接口，所有操作保持用户隔离。
> 验证标记：正式后端已在临时账号中通过详情、切片、MD5 列表、按文件名/MD5 删除、清空、跨账号隔离及数据库切片清理检查；临时数据已清理。

## 1. 本篇目标与对齐边界

接通知识库页面剩余的详情、切片、按文件名删除、按 MD5 删除和清空接口，所有操作保持用户隔离。

参考项目会联动向量/图谱清理；当前只存在 MySQL 文档与切片，所以本篇删除也只处理这两张表，后续接入索引时必须同步扩展。

本篇只动后端。原项目的前端已经直接复制到复刻目录；你无需新建或修改前端文件。后端讲解沿真实的 `router → schema → service → model/数据库` 关系进行，不重复已掌握的 Python 基础语法。

## 2. 目录与文件变化

本篇沿用现有 `backend/app` 目录；只有下表标为【新增文件】的路径需要新建。修改已有文件时，diff 仅显示本篇变化，`+`、`-` 不能复制进源码。

| 标记 | 文件 | 职责 |
|---|---|---|
| 【修改】 | `backend/app/schemas/models.py` | 请求/响应字段与校验 |
| 【修改】 | `backend/app/services/knowledge_service.py` | 用户范围内的业务与事务 |
| 【修改】 | `backend/app/router/knowledge_router.py` | HTTP 路径、依赖和响应 |

## 3. 按顺序操作

终端执行位置：

```text
.
```

```bash
cd "."
```

本篇验证沿用第 17 篇取得的 `RAG_TOKEN`。如果换了终端，请先按[第 17 篇第 3 节](17-note-category-stats.md#3-按顺序操作)重新取得令牌；不要把密码或令牌写入 Markdown。

### 步骤 1：【修改】 `backend/app/schemas/models.py`

**编辑文件的完整地址：**

```text
./backend/app/schemas/models.py
```

**修改定位与前后对照：** 按 diff 的上下文定位已有函数或导入位置；本篇不重复展示整份修改后文件。

```diff
--- backend/app/schemas/models.py（修改前）
+++ backend/app/schemas/models.py（修改后）
@@ -131,3 +131,41 @@
 class KnowledgeListResponse(BaseModel):
     documents: list[KnowledgeDocumentResponse]
     total_count: int
+
+
+class KnowledgeChunkResponse(BaseModel):
+    chunk_id: str
+    index: int
+    content: str
+    page: int | None = None
+    images: list[str] = Field(default_factory=list)
+
+
+class KnowledgeDocumentDetail(BaseModel):
+    id: str
+    filename: str
+    user_id: str
+    md5: str
+    chunk_count: int
+    content: str
+    chunks: list[KnowledgeChunkResponse]
+    images: list[str] = Field(default_factory=list)
+    created_at: datetime
+
+
+class DocumentChunksResponse(BaseModel):
+    filename: str
+    total_chunks: int
+    chunks: list[KnowledgeChunkResponse]
+
+
+class MD5Record(BaseModel):
+    md5: str
+    filename: str
+    original_filename: str
+    upload_time: str
+
+
+class MD5ListResponse(BaseModel):
+    records: list[MD5Record]
+    total_count: int
```

**整体解释：** 详情响应不仅有全文，还有 `chunks` 和 `images` 列表，正好对应前端抽屉的“正文/切片”两种视图。当前 TXT/MD 没有页码和图片，所以 `page=None`、`images=[]`；这些空值是实际能力边界，不伪造 PDF 图像。MD5 列表记录把同一张文档表中的指纹、文件名和上传时间整理出来，没有另建一套会漂移的索引文件。

### 步骤 2：【修改】 `backend/app/services/knowledge_service.py`

**编辑文件的完整地址：**

```text
./backend/app/services/knowledge_service.py
```

**修改定位与前后对照：** 按 diff 的上下文定位已有函数或导入位置；本篇不重复展示整份修改后文件。

```diff
--- backend/app/services/knowledge_service.py（修改前）
+++ backend/app/services/knowledge_service.py（修改后）
@@ -3,17 +3,116 @@
 from hashlib import md5
 from uuid import uuid4
 
-from sqlalchemy import or_, select
+from sqlalchemy import delete, or_, select
 from sqlalchemy.exc import IntegrityError
 from sqlalchemy.ext.asyncio import AsyncSession
 
 from app.core.failed_response import BusinessException
 from app.models.knowledge_document import KnowledgeChunk, KnowledgeDocument
-from app.schemas.models import KnowledgeDocumentResponse, KnowledgeListResponse
+from app.schemas.models import (
+    DocumentChunksResponse, KnowledgeChunkResponse, KnowledgeDocumentDetail,
+    KnowledgeDocumentResponse, KnowledgeListResponse, MD5ListResponse, MD5Record,
+)
 from app.services.document_parser import parse_text_document, split_text
 
 
 class KnowledgeService:
+    async def _find_document(
+        self, db: AsyncSession, user_id: str, filename: str
+    ) -> KnowledgeDocument | None:
+        return await db.scalar(select(KnowledgeDocument).where(
+            KnowledgeDocument.user_id == user_id,
+            KnowledgeDocument.filename == filename,
+        ))
+
+    async def _chunks(
+        self, db: AsyncSession, document_id: str
+    ) -> list[KnowledgeChunkResponse]:
+        result = await db.execute(
+            select(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id)
+            .order_by(KnowledgeChunk.index.asc())
+        )
+        return [KnowledgeChunkResponse(
+            chunk_id=chunk.id, index=chunk.index, content=chunk.content,
+            page=chunk.page, images=chunk.images or [],
+        ) for chunk in result.scalars().all()]
+
+    async def get_detail(
+        self, db: AsyncSession, user_id: str, filename: str
+    ) -> KnowledgeDocumentDetail | None:
+        document = await self._find_document(db, user_id, filename)
+        if document is None:
+            return None
+        chunks = await self._chunks(db, document.id)
+        return KnowledgeDocumentDetail(
+            id=document.id, filename=document.filename, user_id=document.user_id,
+            md5=document.md5, chunk_count=len(chunks), content=document.content, chunks=chunks,
+            created_at=document.created_at,
+        )
+
+    async def get_chunks(
+        self, db: AsyncSession, user_id: str, filename: str
+    ) -> DocumentChunksResponse | None:
+        document = await self._find_document(db, user_id, filename)
+        if document is None:
+            return None
+        chunks = await self._chunks(db, document.id)
+        return DocumentChunksResponse(
+            filename=document.filename, total_chunks=len(chunks), chunks=chunks
+        )
+
+    async def delete_document(
+        self, db: AsyncSession, user_id: str, filename: str
+    ) -> bool:
+        document = await self._find_document(db, user_id, filename)
+        if document is None:
+            return False
+        # 【新增】先删子切片，再删父文档；只提交一次。
+        await db.execute(delete(KnowledgeChunk).where(
+            KnowledgeChunk.document_id == document.id
+        ))
+        await db.delete(document)
+        await db.commit()
+        return True
+
+    async def delete_by_md5(
+        self, db: AsyncSession, user_id: str, md5_value: str
+    ) -> bool:
+        document = await db.scalar(select(KnowledgeDocument).where(
+            KnowledgeDocument.user_id == user_id,
+            KnowledgeDocument.md5 == md5_value,
+        ))
+        return False if document is None else await self.delete_document(
+            db, user_id, document.filename
+        )
+
+    async def clean_all(self, db: AsyncSession, user_id: str) -> int:
+        result = await db.execute(select(KnowledgeDocument.id).where(
+            KnowledgeDocument.user_id == user_id
+        ))
+        ids = list(result.scalars().all())
+        if not ids:
+            return 0
+        await db.execute(delete(KnowledgeChunk).where(
+            KnowledgeChunk.document_id.in_(ids)
+        ))
+        await db.execute(delete(KnowledgeDocument).where(
+            KnowledgeDocument.user_id == user_id
+        ))
+        await db.commit()
+        return len(ids)
+
+    async def list_md5(self, db: AsyncSession, user_id: str) -> MD5ListResponse:
+        result = await db.execute(select(KnowledgeDocument).where(
+            KnowledgeDocument.user_id == user_id
+        ).order_by(KnowledgeDocument.created_at.desc()))
+        records = [MD5Record(
+            md5=document.md5, filename=document.filename,
+            original_filename=document.filename,
+            upload_time=document.created_at.isoformat(),
+        ) for document in result.scalars().all()]
+        return MD5ListResponse(records=records, total_count=len(records))
+
     async def add_document(
         self, db: AsyncSession, user_id: str, filename: str, raw: bytes
     ) -> KnowledgeDocumentResponse:
```

**整体解释：** 服务把 `user_id` 和 `filename` 一起作为查找钥匙，再按 `document_id` 顺序读取切片。详情不存在时返回 `None`，由路由转成 404；这比返回空正文更容易看清失败。删除先删这份文档的切片，再删文档，只提交一次；清空时先收集本人的文档 ID，再批量删这些 ID 对应的切片和本人文档。按 MD5 删除也先在当前用户范围内找记录，然后复用按名删除，避免绕过隔离。若某一步数据库执行失败，本次会话回滚，不会故意留下孤儿切片。

### 步骤 3：【修改】 `backend/app/router/knowledge_router.py`

**编辑文件的完整地址：**

```text
./backend/app/router/knowledge_router.py
```

**修改定位与前后对照：** 按 diff 的上下文定位已有函数或导入位置；本篇不重复展示整份修改后文件。

```diff
--- backend/app/router/knowledge_router.py（修改前）
+++ backend/app/router/knowledge_router.py（修改后）
@@ -2,7 +2,7 @@
 
 import json
 
-from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
+from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
 from fastapi.responses import JSONResponse, StreamingResponse
 from sqlalchemy.ext.asyncio import AsyncSession
 
@@ -87,3 +87,66 @@
 ) -> JSONResponse:
     data = await knowledge_service.list_documents(db, user_id)
     return success_response(data=data)
+
+
+@knowledge_router.get("/detail")
+async def get_document_detail(
+    filename: str = Query(min_length=1),
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> JSONResponse:
+    detail = await knowledge_service.get_detail(db, user_id, filename)
+    if detail is None:
+        raise HTTPException(status_code=404, detail="文档不存在")
+    return success_response(data=detail)
+
+
+@knowledge_router.get("/chunks")
+async def get_document_chunks(
+    filename: str = Query(min_length=1),
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> JSONResponse:
+    chunks = await knowledge_service.get_chunks(db, user_id, filename)
+    if chunks is None:
+        raise HTTPException(status_code=404, detail="文档不存在")
+    return success_response(data=chunks)
+
+
+@knowledge_router.get("/md5/list")
+async def list_md5_records(
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> JSONResponse:
+    return success_response(data=await knowledge_service.list_md5(db, user_id))
+
+
+@knowledge_router.delete("/delete/filename")
+async def delete_by_filename(
+    filename: str = Query(min_length=1),
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> JSONResponse:
+    if not await knowledge_service.delete_document(db, user_id, filename):
+        raise HTTPException(status_code=404, detail="文档不存在")
+    return success_response(message="文档及切片已删除")
+
+
+@knowledge_router.delete("/md5/delete/{md5_value}")
+async def delete_by_md5(
+    md5_value: str,
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> JSONResponse:
+    if not await knowledge_service.delete_by_md5(db, user_id, md5_value):
+        raise HTTPException(status_code=404, detail="文档不存在")
+    return success_response(message="文档及切片已删除")
+
+
+@knowledge_router.delete("/clean")
+async def clean_knowledge(
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> JSONResponse:
+    deleted = await knowledge_service.clean_all(db, user_id)
+    return success_response(message=f"成功删除 {deleted} 份文档")
```

**整体解释：** 接口像不同检索窗口：`/detail?filename=...` 和 `/chunks?filename=...` 读，`/delete/filename?filename=...`、`/md5/delete/{md5}`、`/clean` 写。每个窗口都先调用相同的鉴权依赖，再把后端确定的用户 ID 交给服务；客户端不能从 URL 指定别人的用户。`/clean` 会删除当前用户**全部**知识文档，验证时应使用专门练习账号并先看列表。原前端的删除按钮与这些固定 URL 已对应，前端无需重写。

## 4. 这些文件怎样连成一次请求

点一份文档 → 前端以文件名请求 `/knowledge/detail` → 后端按用户+文件名查文档、按文档 ID 查切片 → 抽屉显示正文和每段文本。点删除 → 同一范围内删切片再删文档 → 列表刷新。用另一个账号的 token 查同名文件，应返回 404，而不会透露对方内容。

## 5. 运行与验证

先完成上述文件操作；若后端尚未运行，在复刻 `backend` 执行 `uv run uvicorn main:app --reload --host 127.0.0.1 --port 8100`，另开终端执行下列命令。命令中的 `RAG_TOKEN` 是第 3 节取得的本机变量。

```bash
TEST_FILE="guide26-$(date +%s).md"
printf '# 第26篇验证\n这是一份临时文档。\n' > "/tmp/$TEST_FILE"
curl -sS -X POST http://127.0.0.1:8100/knowledge/add/single -H "Authorization: Bearer $RAG_TOKEN" -F "file=@/tmp/$TEST_FILE" | python3 -m json.tool
curl -sS -G http://127.0.0.1:8100/knowledge/detail --data-urlencode "filename=$TEST_FILE" -H "Authorization: Bearer $RAG_TOKEN" | python3 -m json.tool
curl -sS -G http://127.0.0.1:8100/knowledge/chunks --data-urlencode "filename=$TEST_FILE" -H "Authorization: Bearer $RAG_TOKEN" | python3 -m json.tool
curl -sS http://127.0.0.1:8100/knowledge/md5/list -H "Authorization: Bearer $RAG_TOKEN" | python3 -m json.tool
curl -sS -X DELETE -G http://127.0.0.1:8100/knowledge/delete/filename --data-urlencode "filename=$TEST_FILE" -H "Authorization: Bearer $RAG_TOKEN" | python3 -m json.tool
rm "/tmp/$TEST_FILE"
```

**预期观察：** 详情含 `content`、`chunks`、`images: []`；切片接口 `total_chunks` 与列表的 `chunk_count` 一致。删除后再查详情应是 HTTP 404，MD5 列表不再有该文档。`DELETE /knowledge/clean` 会删光当前用户知识库，本篇不要对非练习账号执行。

**排查顺序：** 先看后端终端是否成功启动，再看 URL 与方法、Bearer 令牌、请求字段和响应的 HTTP 状态及 `code`。`401` 先查登录/Redis；`422` 先查路径或请求模型；业务 `code` 非 200 先读 `message`；MySQL 异常再查数据库连接和表结构。不要在未确认错误位置时修改前端。

## 6. 工程面试思考

**为什么每次详情或删除都要同时按 `user_id` 和文件名查？** 文件名只是用户自己起的名字，不是全局授权凭据。若只按文件名查，同名文件可能把另一个账号的正文或切片带出来；若只在路由鉴权而服务查询忘记加用户条件，仍会越权。本篇把用户范围放进服务的查询条件，找不到时统一返回 404。用两个账号各上传文件，再交叉查询和删除，是比“接口返回 200”更有意义的验收。

**为什么删除切片和文档要在一次事务里完成？** 切片的 `document_id` 指向父文档，删除是一项逻辑操作。服务先删子记录再删父记录，最后提交；中途数据库报错时，请求会话回滚，避免只删了一半。数据库外键也设置了级联删除，但服务显式处理子记录使当前行为清楚。未来增加向量索引或图谱后，MySQL 事务无法自动覆盖那些系统；需要可重试的清理任务、幂等标记或补偿机制，并验证部分失败后的恢复。

**`/clean` 在生产环境最大的工程风险是什么？** 它会删除当前用户的全部知识文档，是范围很大的操作。当前实现通过服务端用户 ID 限定范围，验证时只用临时账号；产品化时还应根据实际需求增加二次确认、审计记录、异步任务与恢复方案，并考虑文档很多时长事务和大批量删除的影响。不能把前端弹窗当成唯一保护，因为接口可以绕过页面直接调用。

## 7. 本篇边界与下一篇

第 17–26 篇只是笔记辅助接口和文字知识库的可运行第一段；参考项目的 PDF、DOCX、PPTX、图片、Embedding、Neo4j、RAG 与 Agent 都未在这些篇目实现。

下一阶段应补格式解析与可恢复的后台任务，再接向量/图谱索引和有来源的检索。
