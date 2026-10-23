# 第 17 篇：按当前用户统计笔记分类

> 前置：第 16 篇完成后的后端状态。本篇步骤 1、2 已写入正式复刻后端。
> 成果：让原前端的 `GET /note/stats` 真正返回笔记总数、每个分类的数量以及未分类数量。
> 验证标记：已在正式复刻后端通过语法、路由顺序和统计逻辑检查；真实接口中账号 123、456 均返回 HTTP 200，未登录返回 401。第 20 篇联调时还用真实临时笔记验证了非空分类数量，随后已清理。

## 1. 本篇目标与对齐边界

让原前端的 `GET /note/stats` 真正返回笔记总数、每个分类的数量以及未分类数量。

对齐参考项目的分类统计接口；本章只读取 MySQL，不改动笔记。

本篇只动后端。原项目的前端已经直接复制到复刻目录；你无需新建或修改前端文件。后端讲解沿真实的 `router → schema → service → model/数据库` 关系进行，不重复已掌握的 Python 基础语法。

## 2. 目录与文件变化

本篇沿用现有 `backend/app` 目录；只有下表标为【新增文件】的路径需要新建。修改已有文件时，diff 仅显示本篇变化，`+`、`-` 不能复制进源码。

| 标记 | 文件 | 职责 |
|---|---|---|
| 【修改】 | `backend/app/services/note_service.py` | 用户范围内的业务与事务 |
| 【修改】 | `backend/app/router/note_router.py` | HTTP 路径、依赖和响应 |

## 3. 按顺序操作

终端位置：

```text
.
```

```bash
cd "."
```

下面的接口验证使用 `RAG_TOKEN`，它是登录后获得的 JWT。第一次做这一阶段，或换了终端后，可在 **zsh** 中执行以下命令；密码只输入在当前终端，不写进教程、源码或 Git：

```bash
read -rs 'RAG_PASSWORD?输入本地练习账号 123 的密码: '
RAG_TOKEN="$(RAG_PASSWORD="$RAG_PASSWORD" python3 -c 'import json,os; print(json.dumps({"username":"123","password":os.environ["RAG_PASSWORD"]}))' | curl -sS -X POST http://127.0.0.1:8100/user/login/ -H 'Content-Type: application/json' --data-binary @- | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')"
unset RAG_PASSWORD
test -n "$RAG_TOKEN" && echo '已取得练习账号令牌'
```

如果登录响应没有 `token`，先确认复刻后端、MySQL、Redis 已运行，再检查用户名和密码。这里的练习账号由你前面要求创建；不将令牌粘贴进文档。运行后端的终端保持打开；本篇新增路由若未生效，重启 `backend` 中的 `uv run uvicorn main:app --reload --host 127.0.0.1 --port 8100`。

### 步骤 1：【修改】 `backend/app/services/note_service.py`

**编辑文件的完整地址：**

```text
./backend/app/services/note_service.py
```

**修改定位与前后对照：** 按 diff 的上下文定位已有函数或导入位置；本篇不重复展示整份修改后文件。

```diff
--- backend/app/services/note_service.py（修改前）
+++ backend/app/services/note_service.py（修改后）
@@ -32,6 +32,24 @@
         statement = select(Note).where(Note.id == note_id, Note.user_id == user_id)
         result = await db.execute(statement)
         return result.scalar_one_or_none()
+
+    async def get_category_stats(self, db: AsyncSession, user_id: str) -> dict:
+        # 【新增】先按当前用户分组，再从同一份结果算总数和未分类数。
+        result = await db.execute(
+            select(Note.category, func.count(Note.id))
+            .where(Note.user_id == user_id)
+            .group_by(Note.category)
+        )
+        categories = []
+        uncategorized = 0
+        total = 0
+        for category, count in result.all():
+            total += count
+            if not category:
+                uncategorized += count
+            else:
+                categories.append({"category": category, "count": count})
+        return {"total": total, "categories": categories, "uncategorized": uncategorized}
 
     async def list_notes(
         self,
```

**整体解释：** 统计服务像仓库盘点员：它先拿到后端鉴权产生的 `user_id`，只对该用户的笔记分组。每组同时有分类名和数量，所以一次查询的结果就能算出 `total`、`categories` 和 `uncategorized`；空值或空字符串都计入未分类。这里没有先把所有笔记正文搬到 Python，数据库只返回分组与计数。若令牌无效，请求在进入此方法前就被拒绝。

### 步骤 2：【修改】 `backend/app/router/note_router.py`

**编辑文件的完整地址：**

```text
./backend/app/router/note_router.py
```

**修改定位与前后对照：** 按 diff 的上下文定位已有函数或导入位置；本篇不重复展示整份修改后文件。

```diff
--- backend/app/router/note_router.py（修改前）
+++ backend/app/router/note_router.py（修改后）
@@ -42,6 +42,15 @@
         total_count=total_count,
     )
     return success_response(data=data)
+
+
+@note_router.get("/stats")
+async def get_note_stats(
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> JSONResponse:
+    # 【新增】统计只看当前令牌所属用户的笔记。
+    return success_response(data=await note_service.get_category_stats(db, user_id))
 
 
 @note_router.get("/{note_id}")
```

**整体解释：** 路由是这张统计单的领取窗口：`/note/stats` 接到请求后先由 `get_current_user_id` 确认是谁，再由 `get_db` 提供会话，最后把服务结果装进原有 `{code,message,data}` 格式。固定路径必须位于 `/{note_id}` 前；否则 `stats` 可能被误认为一篇笔记的 ID。它只读取，不会提交事务。

## 4. 这些文件怎样连成一次请求

浏览器的笔记列表请求 `/note/stats` → Vite 转发到 8100 → 路由鉴权得出用户 ID → 服务按 `notes.user_id` 分组计数 → `data.categories` 回到前端，分类管理面板据此显示数量。你可以先记住一条：前端传来的分类名称只是筛选建议，统计范围始终由令牌确定。

## 5. 运行与验证

先完成上述文件操作；若后端尚未运行，在复刻 `backend` 执行 `uv run uvicorn main:app --reload --host 127.0.0.1 --port 8100`，另开终端执行下列命令。命令中的 `RAG_TOKEN` 是第 3 节取得的本机变量。

```bash
curl -sS http://127.0.0.1:8100/note/stats -H "Authorization: Bearer $RAG_TOKEN" | python3 -m json.tool
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8100/note/stats
```

**预期观察：** 带有效令牌应为 HTTP 200，`data` 中有 `total`、`categories`、`uncategorized`。练习账号没有笔记时三者分别是 0、空列表、0；不带令牌应为 401。若分类卡片仍为空，先看接口 JSON，而不是先改前端。

**排查顺序：** 先看后端终端是否成功启动，再看 URL 与方法、Bearer 令牌、请求字段和响应的 HTTP 状态及 `code`。`401` 先查登录/Redis；`422` 先查路径或请求模型；业务 `code` 非 200 先读 `message`；MySQL 异常再查数据库连接和表结构。不要在未确认错误位置时修改前端。

## 6. 本篇边界与下一篇

这一章只补分类统计；原前端的搜索、批量和下载仍未由当前正式后端提供。

第 18 篇接通搜索，并明确它与参考项目的语义搜索差别。
