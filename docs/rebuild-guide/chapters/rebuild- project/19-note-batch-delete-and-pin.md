# 第 19 篇：批量删除与批量置顶笔记

> 前置：第 18 篇完成后的后端状态。本篇已写入正式复刻后端。
> 成果：接通 `POST /note/batch/delete` 与 `PUT /note/batch/pin`，一次处理至多 100 个不重复笔记 ID。
> 验证标记：真实 MySQL 中已验证重复 ID 返回 422、批量置顶和删除，以及混入其他账号 ID 时只处理本人的笔记；临时笔记已清理。

## 1. 本篇目标与对齐边界

接通 `POST /note/batch/delete` 与 `PUT /note/batch/pin`，一次处理至多 100 个不重复笔记 ID。

路径、请求字段与参考前端一致；图谱与回顾表尚未建立，本阶段只修改 MySQL `notes` 表。

本篇只动后端。原项目的前端已经直接复制到复刻目录；你无需新建或修改前端文件。后端讲解沿真实的 `router → schema → service → model/数据库` 关系进行，不重复已掌握的 Python 基础语法。

## 2. 目录与文件变化

本篇沿用现有 `backend/app` 目录；只有下表标为【新增文件】的路径需要新建。修改已有文件时，diff 仅显示本篇变化，`+`、`-` 不能复制进源码。

| 标记 | 文件 | 职责 |
|---|---|---|
| 【修改】 | `backend/app/schemas/models.py` | 请求/响应字段与校验 |
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

### 步骤 1：【修改】 `backend/app/schemas/models.py`

**编辑文件的完整地址：**

```text
./backend/app/schemas/models.py
```

**修改定位与前后对照：** 按 diff 的上下文定位已有函数或导入位置；本篇不重复展示整份修改后文件。

```diff
--- backend/app/schemas/models.py（修改前）
+++ backend/app/schemas/models.py（修改后）
@@ -92,3 +92,18 @@
 
 class NoteTemplateReorder(BaseModel):
     ids: list[str] = Field(min_length=1)
+
+
+class BatchIdsRequest(BaseModel):
+    ids: list[str] = Field(min_length=1, max_length=100)
+
+    @field_validator("ids")
+    @classmethod
+    def no_duplicate_ids(cls, ids: list[str]) -> list[str]:
+        if len(ids) != len(set(ids)):
+            raise ValueError("笔记 ID 不能重复")
+        return ids
+
+
+class BatchPinRequest(BatchIdsRequest):
+    is_pinned: bool
```

**整体解释：** 批量请求模型像一张装有笔记编号的清单：空清单和超过 100 项会在进入服务前被拒绝，重复编号也不能让同一笔记在一次请求里算两遍。`BatchPinRequest` 继承清单规则，再加一个明确的 `is_pinned` 目标值；批量设置与单篇的“切换”不同，前端已经算好整批该置顶还是取消置顶。清单里就算混有别人的 ID，模型本身不知道归属，下一层服务必须继续检查。

### 步骤 2：【修改】 `backend/app/services/note_service.py`

**编辑文件的完整地址：**

```text
./backend/app/services/note_service.py
```

**修改定位与前后对照：** 按 diff 的上下文定位已有函数或导入位置；本篇不重复展示整份修改后文件。

```diff
--- backend/app/services/note_service.py（修改前）
+++ backend/app/services/note_service.py（修改后）
@@ -143,6 +143,31 @@
         await db.commit()
         return True
 
+    async def batch_delete_notes(
+        self, db: AsyncSession, user_id: str, ids: list[str]
+    ) -> int:
+        result = await db.execute(
+            select(Note).where(Note.user_id == user_id, Note.id.in_(ids))
+        )
+        notes = list(result.scalars().all())
+        for note in notes:
+            await db.delete(note)
+        # 【新增】查找与删除在同一请求会话里，只提交一次。
+        await db.commit()
+        return len(notes)
+
+    async def batch_pin_notes(
+        self, db: AsyncSession, user_id: str, ids: list[str], is_pinned: bool
+    ) -> int:
+        result = await db.execute(
+            select(Note).where(Note.user_id == user_id, Note.id.in_(ids))
+        )
+        notes = list(result.scalars().all())
+        for note in notes:
+            note.is_pinned = is_pinned
+        await db.commit()
+        return len(notes)
+
     async def toggle_pin(
         self, db: AsyncSession, note_id: str, user_id: str
     ) -> Note | None:
```

**整体解释：** 服务是实际操作仓库的人：用 `Note.user_id == user_id` 和 `Note.id.in_(ids)` 一起查，得到的只能是当前用户拥有的记录。批量删除逐条标记待删，置顶逐条写入同一个目标布尔值，最后各提交一次。传入不存在或属于别人的 ID 时，它们不在查出的 `notes` 中，因此不会被改动；返回的数量是实际命中的行数，不是清单长度。提交失败时请求级会话会回滚，不能把“已写入 Python 对象”误当成“已持久化”。

### 步骤 3：【修改】 `backend/app/router/note_router.py`

**编辑文件的完整地址：**

```text
./backend/app/router/note_router.py
```

**修改定位与前后对照：** 按 diff 的上下文定位已有函数或导入位置；本篇不重复展示整份修改后文件。

```diff
--- backend/app/router/note_router.py（修改前）
+++ backend/app/router/note_router.py（修改后）
@@ -6,7 +6,10 @@
 
 from app.core.success_response import success_response
 from app.db.db_config import get_db
-from app.schemas.models import NoteCreate, NoteListResponse, NoteResponse, NoteUpdate
+from app.schemas.models import (
+    BatchIdsRequest, BatchPinRequest, NoteCreate, NoteListResponse,
+    NoteResponse, NoteUpdate,
+)
 from app.services.note_service import note_service
 from app.utils.auth_utils import get_current_user_id
 
@@ -42,6 +45,28 @@
         total_count=total_count,
     )
     return success_response(data=data)
+
+
+@note_router.post("/batch/delete")
+async def batch_delete_notes(
+    payload: BatchIdsRequest,
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> JSONResponse:
+    deleted = await note_service.batch_delete_notes(db, user_id, payload.ids)
+    return success_response(message=f"成功删除 {deleted} 篇笔记")
+
+
+@note_router.put("/batch/pin")
+async def batch_pin_notes(
+    payload: BatchPinRequest,
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> JSONResponse:
+    updated = await note_service.batch_pin_notes(
+        db, user_id, payload.ids, payload.is_pinned
+    )
+    return success_response(message=f"成功更新 {updated} 篇笔记的置顶状态")
 
 
 @note_router.get("/search")
```

**整体解释：** 两个固定路径先接住列表页的批量动作，再把已验证的清单和后端取得的用户 ID 交给服务。响应仍用现有成功封套，`message` 报实际处理篇数。把这些路由放在 `/{note_id}` 前面，避免把 `batch` 当作笔记编号；之后的分类与下载路由也遵守同样的顺序。

## 4. 这些文件怎样连成一次请求

前端长按进入多选，点“置顶”时送出 `{ids:[...],is_pinned:true}`；后端只选当前用户的这些笔记并一次提交。点“删除”时也是先按用户过滤再删除，因此知道其他账号的 ID 并不能批量越权。

## 5. 运行与验证

先完成上述文件操作；若后端尚未运行，在复刻 `backend` 执行 `uv run uvicorn main:app --reload --host 127.0.0.1 --port 8100`，另开终端执行下列命令。命令中的 `RAG_TOKEN` 是第 3 节取得的本机变量。

```bash
curl -sS -X POST http://127.0.0.1:8100/note/create -H "Authorization: Bearer $RAG_TOKEN" -H 'Content-Type: application/json' -d '{"title":"第19篇临时笔记","content":"只用于批量操作验证"}' | python3 -m json.tool
# 从上一步响应复制 data.id，填入本机变量后再执行，不要选真实笔记。
NOTE_ID='把上一步的 data.id 粘贴在这里'
curl -sS -X PUT http://127.0.0.1:8100/note/batch/pin -H "Authorization: Bearer $RAG_TOKEN" -H 'Content-Type: application/json' -d "{\"ids\":[\"$NOTE_ID\"],\"is_pinned\":true}" | python3 -m json.tool
curl -sS -X POST http://127.0.0.1:8100/note/batch/delete -H "Authorization: Bearer $RAG_TOKEN" -H 'Content-Type: application/json' -d "{\"ids\":[\"$NOTE_ID\"]}" | python3 -m json.tool
```

**预期观察：** 两个批量请求的消息都应报告实际处理 1 篇；再查临时笔记应找不到。验证重复 ID 时会在请求模型阶段返回 422。不要拿正式学习笔记做删除实验。

**排查顺序：** 先看后端终端是否成功启动，再看 URL 与方法、Bearer 令牌、请求字段和响应的 HTTP 状态及 `code`。`401` 先查登录/Redis；`422` 先查路径或请求模型；业务 `code` 非 200 先读 `message`；MySQL 异常再查数据库连接和表结构。不要在未确认错误位置时修改前端。

## 6. 本篇边界与下一篇

将来加回顾记录与图谱后，删除操作还需设计关联清理；本章只承诺当前 `notes` 表。

第 20 篇实现批量改分类与按分类删除，并分清这两个动作。
