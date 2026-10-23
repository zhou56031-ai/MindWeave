# 第 54 篇：让笔记搜索真正使用 Neo4j 语义检索

## 1. 本篇要接通的真实能力

当前笔记搜索仍然使用 MySQL 字面 `contains`，而第 45、46 篇已经把 Chunk 向量和全文索引写入 Neo4j。本篇要把 `/note/search` 改成“先检索 Chunk，再回 MySQL 取完整笔记”，同时补上置顶优先排序。检索只返回当前登录用户的来源，语义命中不能取代 MySQL 的最终归属复核。技术路线见 [Q16](technology-routes/Q16-knowledge-retrieval-routes.md) 与 [Q23](technology-routes/Q23-hybrid-retrieval-and-rerank.md)。

本篇完成后，用户搜索“请求作用域数据库连接”时，可以命中正文写着“每个请求独立创建连接”的笔记，而不是只能命中完全相同的字面字符串。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 文件 | 职责 |
|---:|---|---|---|
| 1 | 【新增文件】 | backend/app/rag/note_search.py | 混合检索 note 来源并回填 MySQL |
| 2 | 【修改】 | backend/app/services/note_service.py | 搜索委托给语义服务，列表置顶优先 |
| 3 | 【新增文件】 | backend/tests/test_semantic_note_search.py | 排序、分页和用户隔离回归 |
| 4 | 【运行验证】 | 两账号语义搜索 | 验证同义表达、置顶和越权 |

固定复刻根目录仍是 `MindWeave`。本篇复用第 46 篇 `hybrid_retrieval.search()`；不要新建第二套向量客户端。

## 3. 按顺序修改文件与验证

### 步骤 1：【新增文件】backend/app/rag/note_search.py

**编辑文件的完整地址：**

~~~text
./backend/app/rag/note_search.py
~~~

**完整文件内容：**

~~~python
"""语义笔记搜索：Neo4j 找候选，MySQL 回填并复核归属。"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.note import Note
from app.rag.hybrid_retrieval import search
from app.services.retrieval_policy import normalize_query


async def semantic_note_search(
    db: AsyncSession,
    user_id: str,
    query: str,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Note], int]:
    keyword = normalize_query(query)
    hits = await search(db, user_id, keyword)
    note_ids: list[str] = []
    for hit in hits:
        if hit.source_kind == "note" and hit.source_id not in note_ids:
            note_ids.append(hit.source_id)
    if not note_ids:
        return [], 0

    rows = await db.execute(select(Note).where(
        Note.user_id == user_id,
        Note.id.in_(note_ids),
    ))
    notes_by_id = {note.id: note for note in rows.scalars().all()}
    ordered = [notes_by_id[note_id] for note_id in note_ids if note_id in notes_by_id]
    offset = (page - 1) * page_size
    return ordered[offset:offset + page_size], len(ordered)
~~~

**整体解释：** 这像图书馆先根据语义索引找到几本书的编号，再回书架确认书还在、而且确实属于当前借阅者。Neo4j 的 Chunk 负责“可能相关”，MySQL 的 `user_id` 条件负责最终事实和权限；如果文档已经删除，回填时不会复活它。当前混合检索最多返回 5 个 Chunk 来源，因此语义搜索页更接近“Top 结果搜索”，不是全库分页搜索；大规模检索应在后续改成独立分页索引。

### 步骤 2：【修改】backend/app/services/note_service.py

**编辑文件的完整地址：**

~~~text
./backend/app/services/note_service.py
~~~

**修改定位与前后对照：** 删除字面搜索正文，委托 `semantic_note_search`；在 `list_notes` 的排序前加入置顶字段。

~~~diff
+from app.rag.note_search import semantic_note_search
 from app.services.review_schedule import first_due_at, utc_naive_now
@@
     async def search_notes(
         self, db: AsyncSession, user_id: str, query: str,
         page: int = 1, page_size: int = 20,
     ) -> tuple[list[Note], int]:
-        keyword = query.strip()
-        if not keyword:
-            raise BusinessException(code=4001, message="搜索词不能为空")
-        conditions = (
-            Note.user_id == user_id,
-            or_(
-                Note.title.contains(keyword, autoescape=True),
-                Note.content.contains(keyword, autoescape=True),
-            ),
-        )
-        total = int((await db.execute(
-            select(func.count(Note.id)).where(*conditions)
-        )).scalar_one())
-        result = await db.execute(
-            select(Note).where(*conditions)
-            .order_by(Note.updated_at.desc(), Note.id.desc())
-            .offset((page - 1) * page_size).limit(page_size)
-        )
-        return list(result.scalars().all()), total
+        return await semantic_note_search(db, user_id, query, page, page_size)
@@
-        statement = select(Note).where(*conditions).order_by(primary_order, Note.id.desc())
+        statement = select(Note).where(*conditions).order_by(
+            Note.is_pinned.desc(), primary_order, Note.id.desc(),
+        )
~~~

**整体解释：** `/note/search` 的 HTTP 形状没有变化，前端仍然得到 `NoteListResponse`。变化发生在服务层的候选来源：过去 SQL 直接查找包含关键词的笔记，现在先问 Neo4j，再用当前用户 ID 回 MySQL 取得正文。列表接口同时把置顶放到第一排序位；这样置顶不再是只写进数据库却看不出效果的状态。

### 步骤 3：【新增文件】backend/tests/test_semantic_note_search.py

**编辑文件的完整地址：**

~~~text
./backend/tests/test_semantic_note_search.py
~~~

**完整文件内容：**

~~~python
"""语义笔记搜索的排序和分页回归。"""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.rag.note_search import semantic_note_search


class SemanticNoteSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_preserves_hit_order_and_filters_deleted_notes(self):
        hits = [
            SimpleNamespace(source_kind="note", source_id="n2"),
            SimpleNamespace(source_kind="knowledge_base", source_id="d1"),
            SimpleNamespace(source_kind="note", source_id="missing"),
            SimpleNamespace(source_kind="note", source_id="n1"),
        ]
        notes = [
            SimpleNamespace(id="n1", title="一"),
            SimpleNamespace(id="n2", title="二"),
        ]
        scalars = SimpleNamespace(all=lambda: notes)
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
            scalars=lambda: scalars,
        )))

        with patch("app.rag.note_search.search", AsyncMock(return_value=hits)):
            ordered, total = await semantic_note_search(
                db, "user-1", "查询", page=1, page_size=20,
            )

        self.assertEqual([note.id for note in ordered], ["n2", "n1"])
        self.assertEqual(total, 2)

    async def test_empty_hits_do_not_query_mysql(self):
        db = SimpleNamespace(execute=AsyncMock())
        with patch("app.rag.note_search.search", AsyncMock(return_value=[])):
            notes, total = await semantic_note_search(db, "user-1", "查询")

        self.assertEqual(notes, [])
        self.assertEqual(total, 0)
        db.execute.assert_not_awaited()
~~~

**整体解释：** 回归不启动真实 Neo4j，而是把“检索顺序”明确交给 fake hits。测试能抓住两类常见错误：又把命中顺序按更新时间重排，以及把已删除或非 note 来源塞回列表。真实双账号和向量质量仍要在最后一步验证。

### 步骤 4：【运行验证】同义搜索、置顶与用户隔离

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv run python -m compileall -q app main.py
uv run python -m unittest tests.test_semantic_note_search -v
~~~

用两个账号各建两篇笔记：

- 账号 A：`FastAPI 请求级会话`，正文写“每个请求独立创建连接”。
- 账号 A：`普通数据库笔记`，正文写“连接池配置”。
- 账号 B：标题和正文故意包含同样关键词。

等待 Worker 把任务构建到 `completed`，登录账号 A 请求：

~~~bash
curl -G "http://127.0.0.1:8100/note/search" \
  -H "Authorization: Bearer <账号A令牌>" \
  --data-urlencode "q=请求作用域数据库连接"
~~~

预期命中账号 A 的语义相关笔记，不出现账号 B 标题。把其中一篇置顶后请求 `/note/list`，预期置顶笔记排在最前。若没有语义结果，先查 Neo4j Chunk 是否存在、向量索引是否 `ONLINE`，再查 Worker 任务状态。

