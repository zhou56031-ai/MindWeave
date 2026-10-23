# 第 24 篇：单文件上传、MD5 去重与事务落库

> 前置：第 23 篇解析文件已存在。本篇已代执行到正式复刻目录。
> 成果：接通 `POST /knowledge/add/single`，把 TXT/Markdown 真正写进知识文档表和切片表。
> 验证标记：正式 MySQL 中已通过上传、切片落库、重复拦截、跨账号隔离和无效类型的真实请求检查；测试文档已清理。

**技术路线原理与同类比较：** [Q12：文件名、MD5、SHA-256 与字节复核](technology-routes/Q12-file-deduplication.md)。

## 1. 本篇目标与对齐边界

接通 `POST /knowledge/add/single`，把 TXT/Markdown 真正写进知识文档表和切片表。

参考项目上传后还建立向量与图谱；本篇只有 MySQL 持久化，不返回“向量已生成”的假消息。

本篇只动后端。原项目的前端已经直接复制到复刻目录；你无需新建或修改前端文件。后端讲解沿真实的 `router → schema → service → model/数据库` 关系进行，不重复已掌握的 Python 基础语法。

## 2. 目录与文件变化

本篇沿用现有 `backend/app` 目录；只有下表标为【新增文件】的路径需要新建。修改已有文件时，diff 仅显示本篇变化，`+`、`-` 不能复制进源码。

| 标记 | 文件 | 职责 |
|---|---|---|
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

**先安装本篇新增依赖。执行位置：复刻 `backend`。**

```bash
cd "./backend"
uv add python-multipart
uv export --locked --no-dev --no-emit-project --no-hashes --format requirements.txt --output-file requirements.txt
```

本篇首次使用 FastAPI `File(...)`/`UploadFile`，在复刻 `backend` 执行 `uv add python-multipart`，再按写作规范从锁文件导出 `requirements.txt`；`pyproject.toml`、`uv.lock`、`requirements.txt` 由命令生成，不手抄。

### 步骤 1：【修改】 `backend/app/services/knowledge_service.py`

**编辑文件的完整地址：**

```text
./backend/app/services/knowledge_service.py
```

**修改定位与前后对照：** 按 diff 的上下文定位已有函数或导入位置；本篇不重复展示整份修改后文件。

```diff
--- backend/app/services/knowledge_service.py（修改前）
+++ backend/app/services/knowledge_service.py（修改后）
@@ -1,13 +1,57 @@
 """知识文档的用户范围查询与后续导入服务。"""
 
-from sqlalchemy import select
+from hashlib import md5
+from uuid import uuid4
+
+from sqlalchemy import or_, select
+from sqlalchemy.exc import IntegrityError
 from sqlalchemy.ext.asyncio import AsyncSession
 
-from app.models.knowledge_document import KnowledgeDocument
+from app.core.failed_response import BusinessException
+from app.models.knowledge_document import KnowledgeChunk, KnowledgeDocument
 from app.schemas.models import KnowledgeDocumentResponse, KnowledgeListResponse
+from app.services.document_parser import parse_text_document, split_text
 
 
 class KnowledgeService:
+    async def add_document(
+        self, db: AsyncSession, user_id: str, filename: str, raw: bytes
+    ) -> KnowledgeDocumentResponse:
+        safe_name, content = parse_text_document(filename, raw)
+        digest = md5(raw).hexdigest()
+        existing = await db.scalar(
+            select(KnowledgeDocument.id).where(
+                KnowledgeDocument.user_id == user_id,
+                or_(KnowledgeDocument.filename == safe_name, KnowledgeDocument.md5 == digest),
+            )
+        )
+        if existing is not None:
+            raise BusinessException(code=4002, message="文件名或文件内容已导入")
+        pieces = split_text(content)
+        document = KnowledgeDocument(
+            id=str(uuid4()), user_id=user_id, filename=safe_name,
+            md5=digest, file_size=len(raw), content=content,
+            status="completed", chunk_count=len(pieces),
+        )
+        try:
+            db.add(document)
+            # 【新增】先在当前事务写入父记录，让切片外键有目标；尚未提交。
+            await db.flush()
+            db.add_all([
+                KnowledgeChunk(
+                    id=str(uuid4()), document_id=document.id, index=index,
+                    content=piece, images=[],
+                )
+                for index, piece in enumerate(pieces)
+            ])
+            # 【新增】文档和全部切片一次提交；唯一约束挡住并发重复导入。
+            await db.commit()
+        except IntegrityError as exc:
+            await db.rollback()
+            if exc.orig.args and exc.orig.args[0] == 1062:
+                raise BusinessException(code=4002, message="文件名或文件内容已导入") from exc
+            raise
+        await db.refresh(document)
+        return KnowledgeDocumentResponse.model_validate(document).model_copy(
+            update={"file_type": safe_name.rsplit(".", 1)[-1].lower(), "preview": content[:120]}
+        )
+
     async def list_documents(
         self, db: AsyncSession, user_id: str
     ) -> KnowledgeListResponse:
```

**整体解释：** 导入服务像图书馆的入库员。解析器先把文件变成安全文件名与正文；`md5(raw)` 是内容去重指纹，不是密码哈希。服务只在当前用户范围内查同名或同指纹记录，避免重复；同时数据库的两个唯一约束挡住并发请求在“先查后写”窗口里的重复。新文档先 `flush` 到当前数据库事务，相当于先给“书”建档，让“索引卡”上的外键有可指向的记录；此时还没有提交，其他事务尚看不到这次导入。随后把所有切片加入同一会话，`await db.commit()` 一次提交；若唯一键冲突就回滚并返回明确错误，外键等其他数据库错误则保留原错误，便于排查，不留下只有书没有索引卡的半成品。`chunk_count` 与实际生成数量一致，`status=completed` 仅表示本阶段的文本落库完成，不表示向量或图谱已经建好。

### 步骤 2：【修改】 `backend/app/router/knowledge_router.py`

**编辑文件的完整地址：**

```text
./backend/app/router/knowledge_router.py
```

**修改定位与前后对照：** 按 diff 的上下文定位已有函数或导入位置；本篇不重复展示整份修改后文件。

```diff
--- backend/app/router/knowledge_router.py（修改前）
+++ backend/app/router/knowledge_router.py（修改后）
@@ -1,15 +1,32 @@
 """知识库 HTTP 接口。"""
 
-from fastapi import APIRouter, Depends
+from fastapi import APIRouter, Depends, File, UploadFile
 from fastapi.responses import JSONResponse
 from sqlalchemy.ext.asyncio import AsyncSession
 
 from app.core.success_response import success_response
 from app.db.db_config import get_db
+from app.services.document_parser import MAX_FILE_BYTES
 from app.services.knowledge_service import knowledge_service
 from app.utils.auth_utils import get_current_user_id
 
 knowledge_router = APIRouter(prefix="/knowledge", tags=["knowledge"])
+
+
+@knowledge_router.post("/add/single")
+async def add_single_document(
+    file: UploadFile = File(...),
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> JSONResponse:
+    try:
+        raw = await file.read(MAX_FILE_BYTES + 1)
+        document = await knowledge_service.add_document(
+            db, user_id, file.filename or "", raw
+        )
+    finally:
+        await file.close()
+    return success_response(message="文档导入成功", data=document)
 
 
 @knowledge_router.get("/list")
```

**整体解释：** HTTP 路由读取 multipart 的 `file` 字段，最多读取 `MAX_FILE_BYTES + 1` 字节以识别超限，再把文件名、字节和后端鉴权产生的用户 ID 交给服务；无论成功失败都关闭 `UploadFile`。这里读入的字节是受限文本，不会信任文件名里的路径去写本机文件。服务返回文档摘要后，路由才发出“文档导入成功”。客户端如果传别人的用户编号也无用，因为请求正文没有这个字段。

## 4. 这些文件怎样连成一次请求

curl 或前端发 multipart `file` → FastAPI 解析上传 → 路由读取至 2 MB 上限 → 解析与切片 → 服务检查本人名/MD5 → 文档和切片同一事务提交 → `/knowledge/list` 立即可见。失败时不应出现只有一部分切片的记录。

## 5. 运行与验证

先完成上述文件操作；若后端尚未运行，在复刻 `backend` 执行 `uv run uvicorn main:app --reload --host 127.0.0.1 --port 8100`，另开终端执行下列命令。命令中的 `RAG_TOKEN` 是第 3 节取得的本机变量。

```bash
printf '# 第24篇\n这是待导入的 Markdown 文本。\n' > /tmp/guide24.md
curl -sS -X POST http://127.0.0.1:8100/knowledge/add/single -H "Authorization: Bearer $RAG_TOKEN" -F 'file=@/tmp/guide24.md' | python3 -m json.tool
curl -sS http://127.0.0.1:8100/knowledge/list -H "Authorization: Bearer $RAG_TOKEN" | python3 -m json.tool
# 再传同一文件，核对去重响应：
curl -sS -X POST http://127.0.0.1:8100/knowledge/add/single -H "Authorization: Bearer $RAG_TOKEN" -F 'file=@/tmp/guide24.md' | python3 -m json.tool
```

**预期观察：** 首次响应 `code: 200`，列表多一条 `guide24.md` 且 `chunk_count` 大于 0；重复上传返回业务错误 `code: 4002`，列表条数不增加。若启动时报 multipart 缺依赖，先完成本篇的 `uv add` 与导出命令。

**排查顺序：** 先看后端终端是否成功启动，再看 URL 与方法、Bearer 令牌、请求字段和响应的 HTTP 状态及 `code`。`401` 先查登录/Redis；`422` 先查路径或请求模型；业务 `code` 非 200 先读 `message`；MySQL 异常再查数据库连接和表结构。不要在未确认错误位置时修改前端。

## 6. 本篇边界与下一篇

只存 MySQL 文本和字符切片；前端多文件按钮调用的是流式接口，第 25 篇才接通。MD5 只用于重复内容检测，不作为安全校验或文件真实性证明。

第 25 篇提供前端需要的多文件 SSE 进度流。
