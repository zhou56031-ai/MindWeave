# 第 21 篇：下载单篇 Markdown 与批量 ZIP

> 前置：第 20 篇完成后的后端状态。本篇已代执行到正式复刻目录。
> 成果：让原前端的 `GET /note/{id}/download` 和 `POST /note/batch/download` 返回可保存的真实文件。
> 验证标记：正式后端已通过单篇 Markdown、批量 ZIP 下载及跨账号 404 的真实请求检查；测试笔记已清理。

## 1. 本篇目标与对齐边界

让原前端的 `GET /note/{id}/download` 和 `POST /note/batch/download` 返回可保存的真实文件。

参考项目会把笔记导出为 Markdown，并将多篇打包 ZIP；本章保持这两个媒体类型和 URL，文件名用安全的笔记 ID。

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
@@ -1,4 +1,7 @@
+from io import BytesIO
+import json
 from uuid import uuid4
+from zipfile import ZIP_DEFLATED, ZipFile
 
 from sqlalchemy import func, or_, select
 from sqlalchemy.ext.asyncio import AsyncSession
@@ -192,6 +195,40 @@
         await db.commit()
         return len(notes)
 
+    @staticmethod
+    def _to_markdown(note: Note) -> str:
+        # 【新增】元数据用 JSON 字符串表示，避免标题中的特殊字符破坏 frontmatter。
+        header = [
+            "---",
+            f"title: {json.dumps(note.title, ensure_ascii=False)}",
+            f"category: {json.dumps(note.category or '', ensure_ascii=False)}",
+            f"tags: {json.dumps(note.tags or [], ensure_ascii=False)}",
+            f"created_at: {json.dumps(note.created_at.isoformat())}",
+            "---",
+        ]
+        return "\n".join(header) + "\n\n# " + note.title.replace("\n", " ") + "\n\n" + note.content + "\n"
+
+    async def export_note_markdown(
+        self, db: AsyncSession, user_id: str, note_id: str
+    ) -> str | None:
+        note = await self.get_note(db, note_id, user_id)
+        return self._to_markdown(note) if note is not None else None
+
+    async def batch_export_zip(
+        self, db: AsyncSession, user_id: str, ids: list[str]
+    ) -> bytes:
+        result = await db.execute(
+            select(Note).where(Note.user_id == user_id, Note.id.in_(ids))
+        )
+        by_id = {note.id: note for note in result.scalars().all()}
+        buffer = BytesIO()
+        with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as archive:
+            for note_id in ids:
+                note = by_id.get(note_id)
+                if note is not None:
+                    archive.writestr(f"{note.id}.md", self._to_markdown(note))
+        return buffer.getvalue()
+
     async def toggle_pin(
         self, db: AsyncSession, note_id: str, user_id: str
     ) -> Note | None:
```

**整体解释：** 下载服务像装订员：先按用户 ID 找到被允许导出的笔记，再把标题、分类、标签和创建时间写成 Markdown frontmatter，正文放在标题之后。元数据用 JSON 字符串编码，避免标题里的冒号、引号或换行破坏格式。批量导出先一次查询本人拥有的 ID，按请求顺序把每篇的 `.md` 内容写进内存 ZIP；ZIP 成员使用 ID 命名，既不会重名，也不会把用户标题当作文件路径。没有命中的别人的 ID 会被跳过。

### 步骤 2：【修改】 `backend/app/router/note_router.py`

**编辑文件的完整地址：**

```text
./backend/app/router/note_router.py
```

**修改定位与前后对照：** 按 diff 的上下文定位已有函数或导入位置；本篇不重复展示整份修改后文件。

```diff
--- backend/app/router/note_router.py（修改前）
+++ backend/app/router/note_router.py（修改后）
@@ -1,7 +1,7 @@
 from typing import Literal
 
-from fastapi import APIRouter, Depends, Query
-from fastapi.responses import JSONResponse
+from fastapi import APIRouter, Depends, HTTPException, Query
+from fastapi.responses import JSONResponse, Response
 from sqlalchemy.ext.asyncio import AsyncSession
 
 from app.core.success_response import success_response
@@ -95,6 +95,34 @@
     )
 
 
+@note_router.post("/batch/download")
+async def batch_download_notes(
+    payload: BatchIdsRequest,
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> Response:
+    data = await note_service.batch_export_zip(db, user_id, payload.ids)
+    return Response(
+        content=data, media_type="application/zip",
+        headers={"Content-Disposition": 'attachment; filename="notes.zip"'},
+    )
+
+
+@note_router.get("/{note_id}/download")
+async def download_note(
+    note_id: str,
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> Response:
+    markdown = await note_service.export_note_markdown(db, user_id, note_id)
+    if markdown is None:
+        raise HTTPException(status_code=404, detail="笔记不存在")
+    return Response(
+        content=markdown.encode("utf-8"), media_type="text/markdown; charset=utf-8",
+        headers={"Content-Disposition": f'attachment; filename="{note_id}.md"'},
+    )
+
+
 @note_router.get("/search")
 async def search_notes(
     q: str = Query(min_length=1, max_length=100),
```

**整体解释：** 单篇下载不是普通 `{code,data}` JSON：它返回 `text/markdown` 字节和 `Content-Disposition`，浏览器才会把它当文件。批量下载同理返回 `application/zip`。单篇找不到时抛 HTTP 404，不能把“笔记不存在”的 JSON 当 Markdown 下载；`Response` 的内容是服务完成用户范围查询之后生成的。前端 `responseType: 'blob'` 正是为接这些二进制响应准备的。

## 4. 这些文件怎样连成一次请求

点单篇下载 → `notesApi.download` 携带 JWT → 后端只按当前用户查笔记 → Markdown 字节返回。多选下载 → `BatchIdsRequest` 限制 ID 数量 → 服务只把本人笔记写入 ZIP → 前端收到 Blob 并触发浏览器保存。

## 5. 运行与验证

先完成上述文件操作；若后端尚未运行，在复刻 `backend` 执行 `uv run uvicorn main:app --reload --host 127.0.0.1 --port 8100`，另开终端执行下列命令。命令中的 `RAG_TOKEN` 是第 3 节取得的本机变量。

```bash
curl -sS -X POST http://127.0.0.1:8100/note/create -H "Authorization: Bearer $RAG_TOKEN" -H 'Content-Type: application/json' -d '{"title":"第21篇导出测试","content":"这段文字应在下载文件中。"}' | python3 -m json.tool
# 复制响应中的 data.id：
NOTE_ID='把上一步的 data.id 粘贴在这里'
curl -sS -D /tmp/guide21-headers.txt -H "Authorization: Bearer $RAG_TOKEN" "http://127.0.0.1:8100/note/$NOTE_ID/download" -o /tmp/guide21.md
curl -sS -X POST http://127.0.0.1:8100/note/batch/download -H "Authorization: Bearer $RAG_TOKEN" -H 'Content-Type: application/json' -d "{\"ids\":[\"$NOTE_ID\"]}" -o /tmp/guide21.zip
unzip -l /tmp/guide21.zip
```

**预期观察：** `/tmp/guide21-headers.txt` 中应有 `text/markdown` 与附件文件名；Markdown 内容含测试文字，ZIP 列表有以该笔记 ID 命名的 `.md`。测试后可删除临时笔记与 `/tmp/guide21*` 文件。

**排查顺序：** 先看后端终端是否成功启动，再看 URL 与方法、Bearer 令牌、请求字段和响应的 HTTP 状态及 `code`。`401` 先查登录/Redis；`422` 先查路径或请求模型；业务 `code` 非 200 先读 `message`；MySQL 异常再查数据库连接和表结构。不要在未确认错误位置时修改前端。

## 6. 本篇边界与下一篇

导出只读当前 MySQL 笔记；文档和图谱数据尚未纳入归档。ZIP 在内存构造，清单最多 100 个 ID，未来大文件批量导出需要流式或后台任务。

第 22 篇建立知识库的文档和切片表，并先接通空列表。
