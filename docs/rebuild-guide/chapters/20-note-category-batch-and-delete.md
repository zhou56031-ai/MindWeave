# 第 20 篇：批量改分类与删除一个分类

> 前置：第 19 篇完成后的后端状态。本篇已写入正式复刻后端。
> 成果：接通 `PUT /note/batch/category` 和 `DELETE /note/category/{category}`。
> 验证标记：真实 MySQL 中已验证批量改分类、分类统计、删除分类及混入其他账号 ID 时的隔离；临时笔记已清理。

## 1. 本篇目标与对齐边界

接通 `PUT /note/batch/category` 和 `DELETE /note/category/{category}`。

接口与参考前端分类管理弹窗的请求对应。删除分类在参考项目会删掉该分类下的笔记，本章沿用这一行为，操作前须确认测试数据。

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
@@ -107,3 +107,7 @@
 
 class BatchPinRequest(BatchIdsRequest):
     is_pinned: bool
+
+
+class BatchCategoryRequest(BatchIdsRequest):
+    category: str = Field(max_length=50)
```

**整体解释：** 批量改分类沿用上一章的 ID 清单校验，再给分类名加长度上限。空字符串有明确含义：把选中的笔记移到未分类；`None` 不是这个请求模型的输入。这里模型只验证字符串形状，服务层继续把更新限定在当前用户拥有的 ID 上。

### 步骤 2：【修改】 `backend/app/services/note_service.py`

**编辑文件的完整地址：**

```text
./backend/app/services/note_service.py
```

**修改定位与前后对照：** 按 diff 的上下文定位已有函数或导入位置；本篇不重复展示整份修改后文件。

```diff
--- backend/app/services/note_service.py（修改前）
+++ backend/app/services/note_service.py（修改后）
@@ -168,6 +168,30 @@
         await db.commit()
         return len(notes)
 
+    async def batch_update_category(
+        self, db: AsyncSession, user_id: str, ids: list[str], category: str
+    ) -> int:
+        result = await db.execute(
+            select(Note).where(Note.user_id == user_id, Note.id.in_(ids))
+        )
+        notes = list(result.scalars().all())
+        for note in notes:
+            note.category = category or None
+        await db.commit()
+        return len(notes)
+
+    async def delete_category(
+        self, db: AsyncSession, user_id: str, category: str
+    ) -> int:
+        result = await db.execute(
+            select(Note).where(Note.user_id == user_id, Note.category == category)
+        )
+        notes = list(result.scalars().all())
+        for note in notes:
+            await db.delete(note)
+        await db.commit()
+        return len(notes)
+
     async def toggle_pin(
         self, db: AsyncSession, note_id: str, user_id: str
     ) -> Note | None:
```

**整体解释：** 同样是操作分类，两个方法的方向完全不同：`batch_update_category` 找到清单里的本人笔记并修改 `category`，正文仍在；`delete_category` 找出本人该分类的所有笔记并删除整行。两个查询都带 `user_id`，提交也分别只发生一次。可以把前者理解为给文件夹里的纸张换标签，后者则是把一个标签下的纸张一并销毁，绝不能在界面或文档里混为“只删标签”。

### 步骤 3：【修改】 `backend/app/router/note_router.py`

**编辑文件的完整地址：**

```text
./backend/app/router/note_router.py
```

**修改定位与前后对照：** 按 diff 的上下文定位已有函数或导入位置；本篇不重复展示整份修改后文件。

```diff
--- backend/app/router/note_router.py（修改前）
+++ backend/app/router/note_router.py（修改后）
@@ -7,7 +7,8 @@
 from app.core.success_response import success_response
 from app.db.db_config import get_db
 from app.schemas.models import (
-    BatchIdsRequest, BatchPinRequest, NoteCreate, NoteListResponse,
+    BatchCategoryRequest, BatchIdsRequest, BatchPinRequest,
+    NoteCreate, NoteListResponse,
     NoteResponse, NoteUpdate,
 )
 from app.services.note_service import note_service
@@ -67,6 +68,31 @@
         db, user_id, payload.ids, payload.is_pinned
     )
     return success_response(message=f"成功更新 {updated} 篇笔记的置顶状态")
+
+
+@note_router.put("/batch/category")
+async def batch_update_category(
+    payload: BatchCategoryRequest,
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> JSONResponse:
+    updated = await note_service.batch_update_category(
+        db, user_id, payload.ids, payload.category
+    )
+    return success_response(message=f"成功更新 {updated} 篇笔记的分类")
+
+
+@note_router.delete("/category/{category}")
+async def delete_category(
+    category: str,
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> JSONResponse:
+    deleted = await note_service.delete_category(db, user_id, category)
+    return success_response(
+        message=f"成功删除分类「{category}」及其 {deleted} 篇笔记",
+        data={"deleted_count": deleted},
+    )
 
 
 @note_router.get("/search")
```

**整体解释：** 路由分别接收 JSON 清单和 URL 中的分类名；后者返回 `data.deleted_count`，让分类管理弹窗知道实际删了多少篇。FastAPI 解码 URL 后再交给服务，SQLAlchemy 参数绑定负责安全地构造查询。固定 `/category/{category}` 应放在动态笔记详情前；没有令牌时仍由鉴权依赖拦截。

## 4. 这些文件怎样连成一次请求

多选两篇笔记选“学习” → `/batch/category` 只更新这两篇的分类。进入管理分类点击删除“学习” → `/category/study` 删除当前用户分类为 `study` 的全部笔记，并把数量放在 `data.deleted_count`。这两个请求对数据库的影响不一样。

## 5. 运行与验证

先完成上述文件操作；若后端尚未运行，在复刻 `backend` 执行 `uv run uvicorn main:app --reload --host 127.0.0.1 --port 8100`，另开终端执行下列命令。命令中的 `RAG_TOKEN` 是第 3 节取得的本机变量。

```bash
curl -sS -X POST http://127.0.0.1:8100/note/create -H "Authorization: Bearer $RAG_TOKEN" -H 'Content-Type: application/json' -d '{"title":"第20篇临时笔记","content":"分类测试","category":"guide20"}' | python3 -m json.tool
curl -sS http://127.0.0.1:8100/note/stats -H "Authorization: Bearer $RAG_TOKEN" | python3 -m json.tool
# 核对 guide20 只含本篇测试记录后，才执行删除：
curl -sS -X DELETE http://127.0.0.1:8100/note/category/guide20 -H "Authorization: Bearer $RAG_TOKEN" | python3 -m json.tool
```

**预期观察：** 创建后 `/note/stats` 应能看到 `guide20`；删除后 `data.deleted_count` 至少为 1，再次统计不应有该分类。批量改分类可用第 19 篇的测试 ID 单独验证，避免对已有笔记误操作。

**排查顺序：** 先看后端终端是否成功启动，再看 URL 与方法、Bearer 令牌、请求字段和响应的 HTTP 状态及 `code`。`401` 先查登录/Redis；`422` 先查路径或请求模型；业务 `code` 非 200 先读 `message`；MySQL 异常再查数据库连接和表结构。不要在未确认错误位置时修改前端。

## 6. 本篇边界与下一篇

这里只处理 MySQL 笔记；日后图谱索引建立后，需要把分类删除和图谱清理协调起来。

第 21 篇补单篇 Markdown 与批量 ZIP 下载，完成笔记列表这一组核心辅助接口。
