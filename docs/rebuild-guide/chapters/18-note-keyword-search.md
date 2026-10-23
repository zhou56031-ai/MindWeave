# 第 18 篇：笔记关键词搜索与用户隔离

> 前置：第 17 篇完成后的后端状态。本篇已写入正式复刻后端。
> 成果：接通 `GET /note/search?q=...`，让复制来的笔记列表能够按标题或正文检索当前用户的笔记。
> 验证标记：真实 MySQL 中已用两个练习账号验证关键词搜索、`%_` 字面匹配、空白搜索词与用户隔离；临时笔记已清理。

**技术路线原理与同类比较：** [Q10：关键词、全文索引与语义检索](technology-routes/Q10-note-search-strategies.md)。

## 1. 本篇目标与对齐边界

接通 `GET /note/search?q=...`，让复制来的笔记列表能够按标题或正文检索当前用户的笔记。

参考项目最终使用 Neo4j Chunk 的语义检索；本章先以 MySQL 字面关键词检索接通页面，图谱和向量阶段再替换搜索内部实现。接口形状保持 `data.notes` 与 `data.total_count`。

本篇只动后端。原项目的前端已经直接复制到复刻目录；你无需新建或修改前端文件。后端讲解沿真实的 `router → schema → service → model/数据库` 关系进行，不重复已掌握的 Python 基础语法。

## 2. 目录与文件变化

本篇沿用现有 `backend/app` 目录；只有下表标为【新增文件】的路径需要新建。修改已有文件时，diff 仅显示本篇变化，`+`、`-` 不能复制进源码。

| 标记 | 文件 | 职责 |
|---|---|---|
| 【修改】 | `backend/app/services/note_service.py` | 用户范围内的业务与事务 |
| 【修改】 | `backend/app/router/note_router.py` | HTTP 路径、依赖和响应 |

## 3. 按顺序操作

终端执行位置：

```text
.
```

```bash
cd "."
```

本篇验证沿用第 17 篇取得的 `RAG_TOKEN`。如果换了终端，请先按[第 17 篇第 3 节](17-note-category-stats.md#3-按顺序操作)重新取得令牌；不要把密码或令牌写入 Markdown。

### 步骤 1：【修改】 `backend/app/services/note_service.py`

**编辑文件的完整地址：**

```text
./backend/app/services/note_service.py
```

**修改定位与前后对照：** 按 diff 的上下文定位已有函数或导入位置；本篇不重复展示整份修改后文件。

```diff
--- backend/app/services/note_service.py（修改前）
+++ backend/app/services/note_service.py（修改后）
@@ -1,6 +1,6 @@
 from uuid import uuid4
 
-from sqlalchemy import func, select
+from sqlalchemy import func, or_, select
 from sqlalchemy.ext.asyncio import AsyncSession
 
 from app.core.failed_response import BusinessException
@@ -50,6 +50,31 @@
             else:
                 categories.append({"category": category, "count": count})
         return {"total": total, "categories": categories, "uncategorized": uncategorized}
+
+    async def search_notes(
+        self, db: AsyncSession, user_id: str, query: str,
+        page: int = 1, page_size: int = 20,
+    ) -> tuple[list[Note], int]:
+        keyword = query.strip()
+        if not keyword:
+            raise BusinessException(code=4001, message="搜索词不能为空")
+        # 【新增】当前用户条件与标题/正文条件必须同时成立。
+        conditions = (
+            Note.user_id == user_id,
+            or_(
+                Note.title.contains(keyword, autoescape=True),
+                Note.content.contains(keyword, autoescape=True),
+            ),
+        )
+        total = int((await db.execute(
+            select(func.count(Note.id)).where(*conditions)
+        )).scalar_one())
+        result = await db.execute(
+            select(Note).where(*conditions)
+            .order_by(Note.updated_at.desc(), Note.id.desc())
+            .offset((page - 1) * page_size).limit(page_size)
+        )
+        return list(result.scalars().all()), total
 
     async def list_notes(
         self,
```

**整体解释：** 把搜索想成在自己的笔记柜里找文字。`query.strip()` 排除全空格输入，`Note.user_id == user_id` 先把柜子锁定在当前用户；标题或正文命中其中一个，就进入候选集。`contains(..., autoescape=True)` 让 `%`、`_` 这些 LIKE 特殊字符按普通文字处理，避免用户输入改变通配范围。总数查询与分页查询用同一组条件，因此 `total_count` 不会把其他用户或其他关键词的记录算进去。这里是字面包含匹配，不能把同义词结果称为语义召回。

### 步骤 2：【修改】 `backend/app/router/note_router.py`

**编辑文件的完整地址：**

```text
./backend/app/router/note_router.py
```

**修改定位与前后对照：** 按 diff 的上下文定位已有函数或导入位置；本篇不重复展示整份修改后文件。

```diff
--- backend/app/router/note_router.py（修改前）
+++ backend/app/router/note_router.py（修改后）
@@ -42,6 +42,21 @@
         total_count=total_count,
     )
     return success_response(data=data)
+
+
+@note_router.get("/search")
+async def search_notes(
+    q: str = Query(min_length=1, max_length=100),
+    page: int = Query(default=1, ge=1),
+    page_size: int = Query(default=20, ge=1, le=100),
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> JSONResponse:
+    notes, total = await note_service.search_notes(db, user_id, q, page, page_size)
+    return success_response(data=NoteListResponse(
+        notes=[NoteResponse.model_validate(note) for note in notes],
+        total_count=total,
+    ))
 
 
 @note_router.get("/stats")
```

**整体解释：** 前端 `notesApi.search(query)` 只传 `q`，路由补上默认第一页和每页 20 条；Pydantic/FastAPI 在业务查询之前拒绝缺失或过长参数。服务返回 ORM 笔记后，`NoteResponse.model_validate` 把可返回字段整理出来，再由 `success_response` 包装。固定 `/search` 放在 `/{note_id}` 前，否则它会落入笔记详情路径。

## 4. 这些文件怎样连成一次请求

在列表输入“RAG” → `NoteList` 调 `notesApi.search` → `/note/search?q=RAG` → 当前用户条件与标题/正文条件同时进入 SQL → 后端返回本页笔记及匹配总量 → 前端刷新卡片。别人的同名笔记不会出现，因为用户条件不是从输入框得到，而是从 JWT 得到。

## 5. 运行与验证

先完成上述文件操作；若后端尚未运行，在复刻 `backend` 执行 `uv run uvicorn main:app --reload --host 127.0.0.1 --port 8100`，另开终端执行下列命令。命令中的 `RAG_TOKEN` 是第 3 节取得的本机变量。

```bash
curl -sS -G http://127.0.0.1:8100/note/search --data-urlencode 'q=RAG' -H "Authorization: Bearer $RAG_TOKEN" | python3 -m json.tool
curl -sS -G http://127.0.0.1:8100/note/search --data-urlencode 'q=%_' -H "Authorization: Bearer $RAG_TOKEN" | python3 -m json.tool
```

**预期观察：** 响应结构应是 `data.notes` 列表与 `data.total_count` 数字；没有匹配时为 `[]` 和 0。输入全空格返回业务错误，不会扫出所有笔记。第二个请求检查 `%`、`_` 被当普通文字。

**排查顺序：** 先看后端终端是否成功启动，再看 URL 与方法、Bearer 令牌、请求字段和响应的 HTTP 状态及 `code`。`401` 先查登录/Redis；`422` 先查路径或请求模型；业务 `code` 非 200 先读 `message`；MySQL 异常再查数据库连接和表结构。不要在未确认错误位置时修改前端。

## 6. 本篇边界与下一篇

本阶段不引入 Embedding/Neo4j，所以搜索结果与参考项目语义检索可能不同；后续检索章只替换服务内部，不改变前端 URL。

第 19 篇让列表的批量删除与批量置顶有真实后端动作。
