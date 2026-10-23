# 第 25 篇：多文件上传的 SSE 进度流

> 前置：第 24 篇完成后的后端状态。本篇已代执行到正式复刻目录。
> 成果：接通原前端实际使用的 `POST /knowledge/add/multiple/stream`，逐文件返回 `processing`、`completed`/`error` 和最终 `finish`。
> 验证标记：正式后端已通过真实 SSE 请求验证事件顺序、重复/不支持文件的错误事件、最终结束事件、最多 5 个文件限制及未登录访问；临时数据已清理。

**技术路线原理与同类比较：** [Q13：SSE、轮询与 WebSocket](technology-routes/Q13-sse-progress-stream.md)。

## 1. 本篇目标与对齐边界

接通原前端实际使用的 `POST /knowledge/add/multiple/stream`，逐文件返回 `processing`、`completed`/`error` 和最终 `finish`。

事件字段与复制来的 `useSSE`、`KnowledgeBase` 页面对齐；本阶段仍只支持 TXT/MD，SSE 的“完成”指 MySQL 存储完成，不代表向量化。

本篇只动后端。原项目的前端已经直接复制到复刻目录；你无需新建或修改前端文件。后端讲解沿真实的 `router → schema → service → model/数据库` 关系进行，不重复已掌握的 Python 基础语法。

## 2. 目录与文件变化

本篇沿用现有 `backend/app` 目录；只有下表标为【新增文件】的路径需要新建。修改已有文件时，diff 仅显示本篇变化，`+`、`-` 不能复制进源码。

| 标记 | 文件 | 职责 |
|---|---|---|
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

### 步骤 1：【修改】 `backend/app/router/knowledge_router.py`

**编辑文件的完整地址：**

```text
./backend/app/router/knowledge_router.py
```

**修改定位与前后对照：** 按 diff 的上下文定位已有函数或导入位置；本篇不重复展示整份修改后文件。

```diff
--- backend/app/router/knowledge_router.py（修改前）
+++ backend/app/router/knowledge_router.py（修改后）
@@ -1,16 +1,67 @@
 """知识库 HTTP 接口。"""
 
-from fastapi import APIRouter, Depends, File, UploadFile
-from fastapi.responses import JSONResponse
+import json
+
+from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
+from fastapi.responses import JSONResponse, StreamingResponse
 from sqlalchemy.ext.asyncio import AsyncSession
 
+from app.core.failed_response import BusinessException
 from app.core.success_response import success_response
-from app.db.db_config import get_db
+from app.db.db_config import AsyncSessionLocal, get_db
 from app.services.document_parser import MAX_FILE_BYTES
 from app.services.knowledge_service import knowledge_service
 from app.utils.auth_utils import get_current_user_id
 
 knowledge_router = APIRouter(prefix="/knowledge", tags=["knowledge"])
+
+
+@knowledge_router.post("/add/multiple/stream")
+async def add_multiple_stream(
+    files: list[UploadFile] = File(...),
+    user_id: str = Depends(get_current_user_id),
+) -> StreamingResponse:
+    if len(files) > 5:
+        raise HTTPException(status_code=422, detail="一次最多上传 5 个文件")
+    pending = []
+    for file in files:
+        try:
+            pending.append((file.filename or "", await file.read(MAX_FILE_BYTES + 1)))
+        finally:
+            await file.close()
+
+    async def events():
+        total = len(pending)
+        for current, (filename, raw) in enumerate(pending, start=1):
+            yield "data: " + json.dumps({
+                "event_type": "processing", "filename": filename,
+                "progress": 10, "current": current, "total": total,
+            }, ensure_ascii=False) + "\n\n"
+            try:
+                # 【新增】流已经开始，逐文件新建会话，失败只影响当前文件。
+                async with AsyncSessionLocal() as db:
+                    await knowledge_service.add_document(db, user_id, filename, raw)
+            except BusinessException as exc:
+                yield "data: " + json.dumps({
+                    "event_type": "error", "filename": filename,
+                    "error_message": exc.message, "current": current, "total": total,
+                }, ensure_ascii=False) + "\n\n"
+            except Exception:
+                yield "data: " + json.dumps({
+                    "event_type": "error", "filename": filename,
+                    "error_message": "文件处理失败", "current": current, "total": total,
+                }, ensure_ascii=False) + "\n\n"
+            else:
+                yield "data: " + json.dumps({
+                    "event_type": "completed", "filename": filename,
+                    "progress": 100, "current": current, "total": total,
+                }, ensure_ascii=False) + "\n\n"
+        yield 'data: {"event_type":"finish"}\n\n'
+
+    return StreamingResponse(
+        events(), media_type="text/event-stream",
+        headers={"Cache-Control": "no-cache"},
+    )
 
 
 @knowledge_router.post("/add/single")
```

**整体解释：** SSE 像柜台边的进度广播。路由先在响应开始前确认用户、限制最多 5 个文件，并把每个上传对象读成受限字节、关闭文件句柄；这样生成器运行时不再依赖已结束的 multipart 请求资源。`events()` 每处理一个文件先发 `processing`，再用独立 `AsyncSessionLocal` 调第 24 篇的入库服务，成功发 `completed`，业务失败发带原因的 `error`，最后一定发 `finish`。前端 `useSSE` 按 `data: ` 开头逐行解析 JSON，并用 `event_type` 更新每个文件的状态，因此事件名必须准确。流一旦开始就不能把某个文件的错误再改成整体 HTTP 422，只能通过该文件的 `error` 事件报告。独立会话使一份文件失败不会回滚前一份已成功提交的文件；这同时意味着整个批次不是一个原子事务。

## 4. 这些文件怎样连成一次请求

用户在知识库页选两个文件 → 浏览器 FormData 重复添加 `files` → Vite 把请求转给后端 → 路由预读文件 → SSE 依次广播处理与结果 → 前端把成功文件标为 100%，失败文件显示原因，收到 `finish` 后刷新文档列表。

## 5. 运行与验证

先完成上述文件操作；若后端尚未运行，在复刻 `backend` 执行 `uv run uvicorn main:app --reload --host 127.0.0.1 --port 8100`，另开终端执行下列命令。命令中的 `RAG_TOKEN` 是第 3 节取得的本机变量。

```bash
printf '第25篇文件A\n' > /tmp/guide25-a.txt
printf '# 第25篇文件B\n' > /tmp/guide25-b.md
curl -sS -N -X POST http://127.0.0.1:8100/knowledge/add/multiple/stream -H "Authorization: Bearer $RAG_TOKEN" -F 'files=@/tmp/guide25-a.txt' -F 'files=@/tmp/guide25-b.md'
curl -sS http://127.0.0.1:8100/knowledge/list -H "Authorization: Bearer $RAG_TOKEN" | python3 -m json.tool
```

**预期观察：** 流里每个文件应先见 `processing`，再见 `completed`；末尾有 `finish`。列表随后出现两份文档。若重复传同一文件，该文件应出现 `error`，但其他新文件仍可完成。

**排查顺序：** 先看后端终端是否成功启动，再看 URL 与方法、Bearer 令牌、请求字段和响应的 HTTP 状态及 `code`。`401` 先查登录/Redis；`422` 先查路径或请求模型；业务 `code` 非 200 先读 `message`；MySQL 异常再查数据库连接和表结构。不要在未确认错误位置时修改前端。

## 6. 工程面试思考

**为什么这里用 SSE 格式的响应流，不直接等所有文件处理完再返回 JSON？** 复制来的前端需要在每份文件处理时显示状态，`fetch` 已能逐行读取 `data: ...`。单个 JSON 只能在整批结束后给结果；轮询则需要额外的任务 ID 和持久状态表。当前处理是短任务、单向进度，流式响应能复用一次上传请求。但它不是后台任务系统：浏览器断开后可能没收到 `completed`，不能据此认定数据库回滚，应重新请求 `/knowledge/list` 确认最终状态。

**第三个文件失败，前两个成功文件怎么办？** 每份文件使用独立会话并各自提交，所以第三个文件发 `error`，前两个仍保留，整批最后发 `finish`。这是为“逐文件导入”选的部分成功语义；如果产品要求整批全成或全败，就需要把文件校验和写入放进一项整体事务，并重新设计进度与错误提示。当前代码只保证单份文件的文档与切片一起提交。

**文件数或文件体积增加后，现有方案会遇到什么？** 路由在开始发送事件前预读最多 5 个、每个最多约 2 MB 的内容，因此内存占用有上界，但上传和预读期间前端看不到后端处理进度。若要支持大量大文件，应改成流式接收或对象存储加后台任务，持久化任务状态，再用 SSE 或轮询读取任务进度；同时要验证断线重连、重试去重和限流。此处的 `processing` 是后端开始处理该文件的标记，不是实际上传字节百分比。

## 7. 本篇边界与下一篇

预读最多 5 × (2 MB + 1) 字节；连接取消时已提交的文件不会自动撤销。真正的后台任务、进度恢复、PDF/Office 解析与向量化仍属于后续阶段。

第 26 篇补齐文档详情、切片、按名/MD5 删除和清空接口。
