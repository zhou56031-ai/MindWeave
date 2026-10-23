# 第 46 篇：向量与全文候选融合，失败时回退字面检索

## 1. 本篇要接通的真实能力

第 45 篇已把 Chunk 向量写入 Neo4j。本篇把向量近邻和全文词项两条候选路线合并，仍只把当前用户资料交给模型，并保留来源 ID。两路分数不能直接相加：一个是余弦分，一个是全文相关度；先按各自名次做 RRF 融合。Neo4j 或嵌入模型不可用时回退第 35 篇 MySQL 字面检索，聊天不因图故障整体失效。技术路线见 [Q23](technology-routes/Q23-hybrid-retrieval-and-rerank.md)。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 文件 | 职责 |
|---:|---|---|---|
| 1 | 【修改】 | backend/app/graph/neo4j_client.py | Chunk 全文索引 |
| 2 | 【新增文件】 | backend/app/rag/hybrid_retrieval.py | 双路召回、RRF、用户过滤 |
| 3 | 【修改】 | backend/app/services/chat_stream_service.py | 改用混合检索 |
| 4 | 【运行验证】 | 临时双用户资料 | 同义词、字面词与故障回退 |

这里的检索目标是候选，不是自动生成真实引用；第 47 篇再把证据和回答分开核对。

## 3. 按顺序修改文件与验证

### 步骤 1：【修改】backend/app/graph/neo4j_client.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/neo4j_client.py
~~~

**修改定位与前后对照：** 在 ensure_graph_schema 的向量索引建立后加全文索引。

~~~diff
     await driver.execute_query(
         "CREATE VECTOR INDEX chunk_embedding_index IF NOT EXISTS "
@@
         dims=settings.EMBEDDING_DIMENSIONS,
     )
+    await driver.execute_query(
+        "CREATE FULLTEXT INDEX chunk_text_index IF NOT EXISTS "
+        "FOR (c:Chunk) ON EACH [c.text]"
+    )
~~~

**整体解释：** 向量索引擅长语义相近，全文字段擅长明确术语。两条索引都只负责快速找候选；Neo4j 的全局索引不会天然替你做多用户隔离，调用查询后仍要检查 node.user_id。若真实资料量增大，应评估分区策略与每用户召回率，不能只加大 limit。

### 步骤 2：【新增文件】backend/app/rag/hybrid_retrieval.py

**编辑文件的完整地址：**

~~~text
./backend/app/rag/hybrid_retrieval.py
~~~

**完整文件内容：**

~~~python
"""Neo4j 双路候选与 MySQL 降级。"""
from fastapi import HTTPException
from neo4j.exceptions import Neo4jError
from sqlalchemy.ext.asyncio import AsyncSession

from app.graph.neo4j_client import graph_driver
from app.rag.embedding import embed
from app.schemas.models import RetrievalHit
from app.services.knowledge_retrieval import knowledge_retrieval
from app.services.retrieval_policy import normalize_query, short_snippet


async def search(
    db: AsyncSession, user_id: str, query: str
) -> list[RetrievalHit]:
    keyword = normalize_query(query)
    try:
        vector = await embed(keyword)
        driver = graph_driver()
        vector_rows = (await driver.execute_query(
            "CALL db.index.vector.queryNodes('chunk_embedding_index', 100, $vector) "
            "YIELD node, score WHERE node.user_id=$uid "
            "RETURN node.id AS id,node.kind AS kind,node.source_id AS sid,"
            "node.source_name AS title,node.text AS text",
            vector=vector, uid=user_id,
        )).records
        word_rows = (await driver.execute_query(
            "CALL db.index.fulltext.queryNodes('chunk_text_index', $q, {limit:100}) "
            "YIELD node, score WHERE node.user_id=$uid "
            "RETURN node.id AS id,node.kind AS kind,node.source_id AS sid,"
            "node.source_name AS title,node.text AS text",
            q=keyword, uid=user_id,
        )).records
    except (HTTPException, Neo4jError, RuntimeError):
        return await knowledge_retrieval.search(db, user_id, keyword)

    fused: dict[str, tuple[int, dict]] = {}
    for rows in (vector_rows, word_rows):
        for rank, row in enumerate(rows, start=1):
            key = row["id"]
            points = int(100000 / (60 + rank))
            previous = fused.get(key)
            fused[key] = (points + (previous[0] if previous else 0), row.data())
    ranked = sorted(fused.values(), key=lambda item: (-item[0], item[1]["id"]))[:5]
    return [
        RetrievalHit(
            source_kind="note" if row["kind"] == "note" else "knowledge_base",
            source_id=row["sid"], title=row["title"] or "",
            snippet=short_snippet(row["text"] or "", keyword),
            score=points,
        )
        for points, row in ranked
    ]
~~~

**整体解释：** 同一个 Chunk 可能被两路找到；字典按 chunk ID 合并，名次靠前者加更多分，再取前五。向量检索和全文索引都先查出最多 100 条候选，再用 user_id 过滤，不能把其他用户文字送给 DeepSeek。全局 top100 在多租户数据很多时可能使某用户候选被别人挤掉，属于本篇清楚承认的召回边界。查询或编码失败时回退 MySQL 字面检索；回退结果仍经过第 35 篇 SQL 用户范围检查。

### 步骤 3：【修改】backend/app/services/chat_stream_service.py

**编辑文件的完整地址：**

~~~text
./backend/app/services/chat_stream_service.py
~~~

**修改定位与前后对照：** 保持 SSE 格式不变，只替换检索入口。

~~~diff
-from app.services.knowledge_retrieval import knowledge_retrieval
+from app.rag.hybrid_retrieval import search as hybrid_search
@@
-            hits = await knowledge_retrieval.search(db, user_id, query[:100])
+            hits = await hybrid_search(db, user_id, query[:100])
~~~

**整体解释：** 聊天服务依旧像流水线的总控：先借数据库会话找当前用户候选，关闭会话后再等待模型。只是“找候选”的内部路线从单一字面升级为双路融合；前端看到的 thinking/response/done 不改。图服务故障时 hybrid_search 会退回旧服务，因而其他页面不受图故障影响。

### 步骤 4：【运行验证】两个用户与两条索引

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv run python -m compileall -q app main.py
~~~

用两个账号建立含相同关键词的临时笔记，等各自 Worker 完成后，分别在聊天里提问。记录检索 hit 的 source_id，任何账号都不能出现另一账号 ID；再关 Neo4j 验证聊天退回 MySQL 字面命中，恢复后查看索引 ONLINE。语义相关性要用固定问题集评估，不以一次“模型答得像”当作检索正确。
