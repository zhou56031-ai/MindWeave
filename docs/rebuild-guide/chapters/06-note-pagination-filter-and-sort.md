# 第 06 篇：把列表升级为分页、分类标签筛选与稳定排序

> 日期：2026-10-20。新版连续教程；面向有 Python、HTTP、JSON 与异步基础的读者。 
> 前置：完成[上一篇](05-note-update-delete-and-pin.md)，从该篇最终文件继续。 
> 本篇成果：GET /note/list 按 page、page_size、category、tag、sort_by 查询；返回当前页 notes 和筛选后的 total_count。 
> 交付范围：本篇是操作教材，代码在独立临时目录验证；不会自动把新增代码写入你的正式复刻目录。

## 1. 本篇目标与操作起点

复刻根目录固定为：

```text
.
```

文中所有 backend/、app/ 等位置都以这里为准，不在上一级参考项目中写代码。用户当前正式项目只执行到新版第 01 篇；本篇及后续篇章需要按顺序完成，不能直接跳到最后一篇复制入口文件。

本篇只修改服务与路由两份文件。第 05 篇的创建、详情、更新、置顶、删除继续保留。当前正式项目若还停在第 01 篇，应先按第 02–05 篇完成，不直接把本篇完整 service/router 粘到缺少模型和数据库的工程。

基础语法直接使用。本篇围绕正在创建的文件说明职责、数据与调用关系，重点解释新机制和为什么这样组织。
## 2. 列表接口的目标约定

| 参数 | 默认与约束 | 业务含义 |
|---|---|---|
| page | 默认 1，至少 1 | 当前请求第几页 |
| page_size | 默认 20，范围 1–100 | 当前页最多多少条 |
| category | 可省略，最多 50 字符 | 只看指定分类 |
| tag | 可省略，非空且最多 50 字符 | 标签列表中精确包含该元素 |
| sort_by | updated_at、created_at、title | 允许的排序字段 |

返回结构不新增另一套格式，继续为 code、message、data；data 中包含 notes 和 total_count。没有命中的结果是空列表和 0，不是接口错误。

更新时间和创建时间按新到旧排序，标题按升序；同一主排序值时用 id 作为稳定的第二排序键。当前没有实现原项目的语义搜索，本篇 category/tag 都是列表过滤，不能把它们称为 RAG 检索。

### 2.1 本次改动清单

| 标记 | 文件与位置 | 改动 |
|---|---|---|
| 【修改 C01】 | NoteService.list_notes | 加入过滤、总数、分页与排序 |
| 【修改 C02】 | router 的 list_notes | 声明 Query 参数，传给服务并使用总数 |
| 【查看】 | NoteListResponse | 现有 notes/total_count 已够用，无需修改 |
| 【查看】 | main.py 与 Note 表 | 无新路由组、无新字段，不改 |

## 3. 先理解查询顺序，再修改文件

正确业务顺序为：限定当前用户 → 分类筛选 → 标签筛选 → 排序 → 计算筛选总量并取页。实际实现会把能够由 SQL 完成的工作交给数据库，标签沿参考阶段做精确内存过滤，但对外语义一致。

最容易出错的是先从数据库拿 20 条，再对这 20 条筛 tag。这样明明后面还有匹配记录，第一页却可能只剩一条，total_count 也容易算错。本篇用两个清楚的分支解决这件事，并交代小数据阶段的性能边界。

不新增文件夹与依赖；打开下面两份已有文件，先看 diff，再用完整代码替换。与上一篇无关的个人修改应先保留并比对，不盲目覆盖。
### 步骤 1：【修改】`backend/app/services/note_service.py`

**编辑文件的完整地址：**

```text
./backend/app/services/note_service.py
```

**修改定位与前后对照：** 根据下列函数名、配置项或导入位置定位；diff 仅供阅读，正负号不要复制进源码。对照以完成上一篇后的版本为准，请按 diff 修改已有文件。

```diff
--- backend/app/services/note_service.py（修改前）
+++ backend/app/services/note_service.py（修改后）
@@ -1,6 +1,6 @@
 from uuid import uuid4
 
-from sqlalchemy import select
+from sqlalchemy import func, select
 from sqlalchemy.ext.asyncio import AsyncSession
 
 from app.core.failed_response import BusinessException
@@ -33,15 +33,46 @@
         result = await db.execute(statement)
         return result.scalar_one_or_none()
 
-    async def list_notes(self, db: AsyncSession, user_id: str) -> list[Note]:
-        statement = (
-            select(Note)
-            .where(Note.user_id == user_id)
-            .order_by(Note.updated_at.desc(), Note.id.desc())
-        )
-        result = await db.execute(statement)
-        return list(result.scalars().all())
+    async def list_notes(
+        self,
+        db: AsyncSession,
+        user_id: str,
+        page: int = 1,
+        page_size: int = 20,
+        category: str | None = None,
+        tag: str | None = None,
+        sort_by: str = "updated_at",
+    ) -> tuple[list[Note], int]:
+        # 【修改 C01】先建立用户范围，任何后续分支都不能丢掉它。
+        conditions = [Note.user_id == user_id]
+        if category is not None:
+            conditions.append(Note.category == category)
 
+        sort_columns = {
+            "updated_at": Note.updated_at,
+            "created_at": Note.created_at,
+            "title": Note.title,
+        }
+        if sort_by not in sort_columns:
+            raise BusinessException(code=4002, message="不支持的排序字段")
+        column = sort_columns[sort_by]
+        primary_order = column.asc() if sort_by == "title" else column.desc()
+        statement = select(Note).where(*conditions).order_by(primary_order, Note.id.desc())
+        offset = (page - 1) * page_size
+
+        if tag is not None:
+            # 【新增】先在当前用户/分类候选中精确匹配标签，再计算总数和切页。
+            result = await db.execute(statement)
+            candidates = list(result.scalars().all())
+            matched = [note for note in candidates if tag in (note.tags or [])]
+            total_count = len(matched)
+            return matched[offset:offset + page_size], total_count
+
+        # 【新增】无标签筛选时，在数据库完成 COUNT、LIMIT 和 OFFSET。
+        count_statement = select(func.count(Note.id)).where(*conditions)
+        total_count = int((await db.execute(count_statement)).scalar_one())
+        result = await db.execute(statement.offset(offset).limit(page_size))
+        return list(result.scalars().all()), total_count
 
     async def update_note(
         self, db: AsyncSession, note_id: str, user_id: str, payload: NoteUpdate
```

**整体解释：** 列表服务在当前用户的笔记范围内筛选分类和标签，计算总数，排序后取一页。像先确认是谁的抽屉，再按条件翻找、数清总量并拿出指定那一叠；若顺序颠倒，分页数量和结果都会失真。原方法一次查出全部记录，现在接收参数并返回二元组“当前页记录、总量”。调用方也必须同时修改，不能让路由继续把这个二元组当 Note 列表逐个转换。conditions 一开始就放 Note.user_id == user_id，分类条件按需追加，普通查询、COUNT 和 tag 分支都复用它。若 COUNT 忘记加用户条件，可能列表看起来隔离正常，数量却泄露了其他用户的数据。客户端提交的是字符串，不能直接拼进 ORDER BY。字典把三个允许的名称映射到实际 ORM 列对象；路由会先校验，服务本身也有检查，以便未来由其他入口调用时仍不接受任意字段。page=1、page_size=20 时 offset=0；第二页 offset=20。SQL 的 limit 是最多返回条数，offset 是从筛选和排序后的结果跳过多少条，不是 note id，也不是数据库物理行号。数据库有 53 条符合筛选的记录，请求第三页每页 20 条，应返回 13 条 notes、total_count=53。若请求第四页，则 notes 为空但 total_count 仍是 53，不能因为这一页空就说总库没有记录。JSON 标签列表中使用 Python 元素匹配，RAG 不会因为 RAG进阶 字符串含有相同片段就命中，rag 也不会自动等于 RAG。先筛选后分页才能让页内数量与总量一致；None 标签视为空列表，不会抛 TypeError。有 tag 时会读取当前用户及分类下全部候选到内存，适合当前小数据教学阶段，参考项目也有内存标签处理。不能把它说成已完成大数据分页优化；后续可用 MySQL JSON 查询或标签关联表把过滤下推，但要保持匹配语义和 total_count 一致。第二排序键避免同一时间戳下顺序不确定，但如果查询期间有新增或修改，基于 offset 的连续翻页仍可能移动结果。需要持续一致的快照或游标分页时应单独设计，本篇不靠一句“稳定排序”声称解决所有并发翻页问题。

### 步骤 2：【修改】`backend/app/router/note_router.py`

**编辑文件的完整地址：**

```text
./backend/app/router/note_router.py
```

**修改定位与前后对照：** 根据下列函数名、配置项或导入位置定位；diff 仅供阅读，正负号不要复制进源码。对照以完成上一篇后的版本为准，请按 diff 修改已有文件。

```diff
--- backend/app/router/note_router.py（修改前）
+++ backend/app/router/note_router.py（修改后）
@@ -1,4 +1,6 @@
-from fastapi import APIRouter, Depends
+from typing import Literal
+
+from fastapi import APIRouter, Depends, Query
 from fastapi.responses import JSONResponse
 from sqlalchemy.ext.asyncio import AsyncSession
 
@@ -25,11 +27,19 @@
 async def list_notes(
     user_id: str = Depends(get_current_user_id),
     db: AsyncSession = Depends(get_db),
+    page: int = Query(default=1, ge=1),
+    page_size: int = Query(default=20, ge=1, le=100),
+    category: str | None = Query(default=None, max_length=50),
+    tag: str | None = Query(default=None, min_length=1, max_length=50),
+    sort_by: Literal["updated_at", "created_at", "title"] = "updated_at",
 ) -> JSONResponse:
-    notes = await note_service.list_notes(db, user_id)
+    # 【修改 C02】接收服务返回的当前页和筛选总数，二者不要混淆。
+    notes, total_count = await note_service.list_notes(
+        db, user_id, page, page_size, category, tag, sort_by
+    )
     data = NoteListResponse(
         notes=[NoteResponse.model_validate(note) for note in notes],
-        total_count=len(notes),
+        total_count=total_count,
     )
     return success_response(data=data)
```

**整体解释：** Query 先在 HTTP 入口检查页码、页大小和排序参数，合格请求才交给服务。服务返回当前页与总数，路由分别装入响应；前端不仅能看到这一页，还能知道后面有没有更多页。原 list 路由增加 Query 参数与 Literal 排序值，调用服务时把参数一一传入，并拆分两个返回值。CRUD 其他函数保持上一篇实现。Query 的 ge/le 先在 HTTP 边界拒绝 page=0、page_size=101；输入字符串 page=abc 也无法转换为整数。非法排序名在路由阶段返回 422，不会作为 SQL 片段进入数据库。这里查询参数来自 URL，而创建/更新的 payload 来自 JSON 正文，两个入口的定位信息不同：分页错误通常在 query/page，标题错误在 body/title。第 02 篇统一错误处理保留 loc，正好能帮助前端定位字段。category 没传为 None，表示不增加分类限制；明确传空字符串则是在查空字符串分类，不自动变成“所有”。tag 设置最小长度，?tag= 会被拒绝。对中文和特殊字符，下面使用 curl --get --data-urlencode，避免直接手拼 URL 导致请求被截断。固定 /list 继续在动态 /{note_id} 之前。修改列表不需要重复 include_router，也不应把已有 CRUD 注释掉；否则看似分页修好了，却让上一章功能退步。

## 4. 用一份具体数据验证思路

假设当前用户有以下四条笔记，标题排序按 A、B、C、D：

| 标题 | 分类 | 标签 |
|---|---|---|
| A-检索 | lesson06 | RAG、学习 |
| B-图谱 | lesson06 | RAG |
| C-计划 | lesson06 | life |
| D-小写 | lesson06 | rag |

查询 category=lesson06、tag=RAG、sort_by=title 后先得到 A、B 两条，再分页。page_size=1 的第一页是 A，第二页是 B，两页 total_count 都是 2。若先分页再筛 tag，某页很容易错误地变成空页，这正是本篇要避免的问题。

分类的字符串比较受数据库排序规则影响；当前 MySQL 使用 utf8mb4_unicode_ci，不能用 SQLite 的默认大小写比较表现替代 MySQL 的分类排序测试。标签分支用 Python 精确匹配，所以大小写行为由这段代码明确决定。

## 5. 创建本篇数据并执行查询

保存两份文件后，等待本项目自动重载，或在 backend 手动启动：
```bash
cd "./backend"
uv run uvicorn main:app --reload --host 127.0.0.1 --port 8100
```
下面会真实新增四条演示笔记。已存在同名或同分类数据时总量可能更大，重复执行也会继续新增；不要为了让数字一样而清空自己的数据库。可以把分类 lesson06 换成你自己本轮独有的分类。

**执行位置：终端 B，任意目录。**
```bash
curl -sS -X POST http://127.0.0.1:8100/note/create -H 'Content-Type: application/json'   -d '{"title":"A-检索","content":"第一条","category":"lesson06","tags":["RAG","学习"]}'
curl -sS -X POST http://127.0.0.1:8100/note/create -H 'Content-Type: application/json'   -d '{"title":"B-图谱","content":"第二条","category":"lesson06","tags":["RAG"]}'
curl -sS -X POST http://127.0.0.1:8100/note/create -H 'Content-Type: application/json'   -d '{"title":"C-计划","content":"第三条","category":"lesson06","tags":["life"]}'
curl -sS -X POST http://127.0.0.1:8100/note/create -H 'Content-Type: application/json'   -d '{"title":"D-小写","content":"第四条","category":"lesson06","tags":["rag"]}'
```
### 5.1 不带标签：数据库分页分支
```bash
curl -i --get http://127.0.0.1:8100/note/list   --data-urlencode 'category=lesson06'   --data-urlencode 'sort_by=title'   --data-urlencode 'page=1'   --data-urlencode 'page_size=2'
```
在该分类只有上述四条的情况下，第一页两条，total_count=4。改 page=2 得到另外两条；改 page=3 得到空 notes，但总量仍是 4。用 SQL 的 COUNT 与本页数组长度分别验证两个数。

### 5.2 带标签：先筛选再分页分支
```bash
curl -i --get http://127.0.0.1:8100/note/list   --data-urlencode 'category=lesson06'   --data-urlencode 'tag=RAG'   --data-urlencode 'sort_by=title'   --data-urlencode 'page=1'   --data-urlencode 'page_size=1'
```
第一页应为 A-检索、total_count=2，第二页 B-图谱、总量依然 2。将 tag 改为 rag，只命中 D-小写；改为一个不存在的标签，结果为空且总量 0。

### 5.3 非法参数应在入口拒绝
```bash
curl -i 'http://127.0.0.1:8100/note/list?page=0'
curl -i 'http://127.0.0.1:8100/note/list?page_size=101'
curl -i 'http://127.0.0.1:8100/note/list?page=abc'
curl -i 'http://127.0.0.1:8100/note/list?sort_by=content'
```
四个请求均应 HTTP 422，data 包含对应 query 字段定位。非法请求不应修改任何笔记，也不应把排序内容拼进 SQL。

### 5.4 回归之前的功能

从本篇创建响应复制一个实际 id，读取详情、修改标题、切换置顶，再查询列表观察字段。仍不需要改 main.py；如果 CRUD 接口消失，优先检查是否只保存了本篇局部列表代码，而丢掉完整文件中的其他处理函数。

应用重启后再次查询 lesson06 分类，数据仍在。数据库容器重启后需要等待健康与连接恢复，再判定查询结果。没有依赖更新或表结构变化，不应为了改分页重建环境或删除数据库。

## 6. 直接从 SQL 和返回值判断问题

| 现象 | 可能遗漏 | 正确检查 |
|---|---|---|
| 每页 total_count 都等于 page_size | 把 len(notes) 当总量 | COUNT 或标签筛选后总量应在分页前计算 |
| 列表只显示本人，数量却偏大 | count 查询少了 user_id | 两条 SQL 复用同一 conditions |
| 标签明明有数据，某页却莫名为空 | 先切页后筛 tag | 先筛选完整候选，再计算总数与页 |
| 标题相同时时而跳动 | 无第二排序键 | 主排序后加 id，另注意并发更新导致页移动 |
| RAG 命中了 RAG进阶 | 使用了字符串子串匹配 | 判断标签列表是否包含元素 |
| 中文分类请求被截断 | URL 编码或 & 被 Shell 解释 | URL 加引号或使用 --data-urlencode |
| 修改后接口报元组不是 Note | 路由没同步拆分返回值 | 使用 notes, total_count 接收 |

**只读 SQL 对照：** 进入复刻 MySQL 后，可核对类别总数：
```sql
SELECT COUNT(*) FROM notes WHERE user_id = 'learning-user' AND category = 'lesson06';
SELECT id, title, tags FROM notes WHERE user_id = 'learning-user' AND category = 'lesson06' ORDER BY title ASC, id DESC LIMIT 2 OFFSET 0;
```
SQL 对照的是无标签分支；本篇标签过滤在 Python 执行，因此不能拿只带分类的 COUNT 当带标签总量。两者查询条件必须相同才有比较意义。

## 7. 本阶段核对与后续安排

- [ ] 普通分页得到正确页与总量，越界页为空但保留总量。
- [ ] 分类与标签组合过滤后，total_count 与完整匹配结果一致。
- [ ] 标签精确匹配，排序白名单与分页边界会拒绝非法输入。
- [ ] 之前所有 CRUD 和健康接口仍可用。
- [ ] 服务与路由两处改动一致，没有增加不必要依赖。

第 02–06 篇完成后，后端已经能通过真实数据库完成核心笔记 CRUD 与列表查询。它仍是单一演示用户阶段，没有 JWT、Redis、完整前端、图谱、AI 标签或语义搜索。下一阶段计划接入真正的账号与身份解析，替换 auth_utils 的演示实现，并增加两个用户的完整访问验证；对应新教程尚未生成。

**参考源码：** [原列表路由](../../../backend/app/router/note_router.py)、[原笔记服务](../../../backend/app/services/note_service.py)。字段与查询参数尽量对齐，临时性能策略和未实现能力以上文为准；原项目的 /note/search 是另一个语义检索入口，当前没有用 SQL 模糊搜索冒充它。

### 本篇验证记录

**已执行流程与 HTTP 验证（2026-10-20，临时 SQLite）**：无标签的 COUNT/LIMIT/OFFSET、分类过滤、越界空页保留总量、带标签先筛选后分页、RAG/rag 精确区分、标题排序及第二排序键、非法页码/页大小/排序值均通过；SQL 注入式排序文本被入口拒绝；重启应用后数据仍在。测试用户覆盖验证了列表与总数均受 user_id 范围限制。

**未实测部分**：MySQL utf8mb4_unicode_ci 的排序与字符串比较、MySQL 真正的事务隔离和容器卷重启。用户尚未把这些教程代码应用到正式复刻项目，正式项目仍停在第 01 篇。

本轮临时验证记录：`/tmp/verification-results.json`。所有验证服务均已停止；正式 8100 服务及其源码不参与本轮变更。
