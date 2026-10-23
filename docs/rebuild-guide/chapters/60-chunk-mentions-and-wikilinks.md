# 第 60 篇：Chunk 级实体提及与笔记双链

## 1. 本篇要接通的真实能力

参考项目不仅能回答“哪份文档提到某实体”，还能回答“哪一个 Chunk 提到了它”，并把 Markdown `[[另一篇笔记]]` 解析成 WIKI 边。复刻项目目前只有 Source 级 MENTIONS，图谱画布看不到双链。本篇补上 Chunk 级实体提及与笔记双链。技术路线见 [Q19](technology-routes/Q19-neo4j-graph-store.md)。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 文件 | 职责 |
|---:|---|---|---|
| 1 | 【新增文件】 | backend/app/graph/link_parser.py | 提取 `[[双链]]` |
| 2 | 【新增文件】 | backend/app/graph/deep_links.py | Chunk 提及与 WIKI 边 |
| 3 | 【修改】 | backend/app/graph/worker.py | 写图后补深链 |
| 4 | 【修改】 | backend/app/graph/views.py | 显示 Note/WIKI 边 |
| 5 | 【运行验证】 | 两份笔记与一个 Chunk | 验证提及与双链 |

## 3. 按顺序修改文件与验证

### 步骤 1：【新增文件】backend/app/graph/link_parser.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/link_parser.py
~~~

**完整文件内容：**

~~~python
"""从 Markdown 笔记提取 [[双链]] 目标标题。"""
import re

LINK = re.compile(r"\[\[([^\]\n]{1,200})\]\]")


def parse_links(content: str) -> list[str]:
    result = []
    for match in LINK.finditer(content or ""):
        title = match.group(1).strip()
        if title and title not in result:
            result.append(title)
    return result[:50]
~~~

**整体解释：** 正则只负责找到用户明确写下的双链语法，不猜测普通文字。目标数量限制为 50，避免异常文本触发无限图写入；目标笔记是否存在仍要在数据库中查询。

### 步骤 2：【新增文件】backend/app/graph/deep_links.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/deep_links.py
~~~

**完整文件内容：**

~~~python
"""Chunk 实体提及与笔记 WIKI 边。"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.graph.link_parser import parse_links
from app.graph.neo4j_client import graph_driver
from app.models.note import Note


async def link_chunk_entities(
    user_id: str, kind: str, source_id: str, texts: list[str],
) -> None:
    rows = (await graph_driver().execute_query(
        "MATCH (e:Entity {user_id:$uid}) RETURN e.id AS id,e.name AS name",
        uid=user_id,
    )).records
    entities = [(row["id"], row["name"].casefold()) for row in rows]
    for index, text in enumerate(texts):
        folded = text.casefold()
        for entity_id, name in entities:
            if name and name in folded:
                await graph_driver().execute_query(
                    "MATCH (c:Chunk {user_id:$uid,kind:$kind,source_id:$sid,chunk_index:$index}) "
                    "MATCH (e:Entity {user_id:$uid,id:$eid}) "
                    "MERGE (c)-[:MENTIONS]->(e)",
                    uid=user_id, kind=kind, sid=source_id,
                    index=index, eid=entity_id,
                )


async def replace_wikilinks(
    db: AsyncSession, user_id: str, note_id: str, title: str, content: str,
) -> None:
    titles = parse_links(content)
    targets = []
    if titles:
        rows = await db.execute(select(Note).where(
            Note.user_id == user_id,
            Note.title.in_(titles),
            Note.id != note_id,
        ))
        targets = [
            {"id": note.id, "title": note.title}
            for note in rows.scalars().all()
        ]
    driver = graph_driver()
    await driver.execute_query(
        "MERGE (n:Note {user_id:$uid,id:$nid}) "
        "SET n.title=$title",
        uid=user_id, nid=note_id, title=title,
    )
    await driver.execute_query(
        "MATCH (:Note {user_id:$uid,id:$nid})-[r:WIKI {user_id:$uid}]->() DELETE r",
        uid=user_id, nid=note_id,
    )
    for target in targets:
        await driver.execute_query(
            "MERGE (a:Note {user_id:$uid,id:$aid}) "
            "MERGE (b:Note {user_id:$uid,id:$bid}) "
            "SET b.title=$title "
            "MERGE (a)-[:WIKI {user_id:$uid,kind:'wiki'}]->(b)",
            uid=user_id, aid=note_id, bid=target["id"], title=target["title"],
        )
~~~

**整体解释：** Chunk 提及使用已经存在的实体名做本地子串匹配，不再调用一次模型。双链只连接同用户真实存在的标题，不把不存在的 `[[标题]]` 造假成节点。WIKI 边按来源先删后建，修改笔记后会替换旧链；当前实现按标题精确匹配，遇到同名笔记时还需要进一步规定唯一选择规则。

### 步骤 3：【修改】backend/app/graph/worker.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/worker.py
~~~

**修改定位与前后对照：** 在实体图和 Chunk 写完后再补深链。

~~~diff
+from app.graph.deep_links import link_chunk_entities, replace_wikilinks
@@
             await replace_source(user_id, kind, source_id, title, result)
             await replace_chunks(user_id, kind, source_id, title, content)
+            await link_chunk_entities(
+                user_id, kind, source_id, split_text(content)[:50],
+            )
+            if kind == "note":
+                async with AsyncSessionLocal() as db:
+                    await replace_wikilinks(db, user_id, source_id, title, content)
~~~

**整体解释：** 顺序不能反过来：Chunk 和 Entity 必须先存在，MENTIONS 才有两端。双链只在 note 来源执行，文档不会产生笔记 WIKI。深链失败会让任务进入重试，下一次仍按来源替换，幂等 MERGE 不会重复累加。

### 步骤 4：【修改】backend/app/graph/views.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/views.py
~~~

**修改定位与前后对照：** 读取 WIKI 边并补充 note 节点。

~~~diff
         manual_rows = (await graph_driver().execute_query(
@@
         edges.extend({
             "id": "manual_relation:" + r["id"],
             "source": r["aid"], "target": r["bid"],
             "kind": "relation", "relation_type": r["kind"],
         } for r in manual_rows)
+        wiki_rows = (await graph_driver().execute_query(
+            "MATCH (a:Note {user_id:$uid})-[r:WIKI {user_id:$uid}]->"
+            "(b:Note {user_id:$uid}) RETURN a.id AS aid,a.title AS atitle,"
+            "b.id AS bid,b.title AS btitle,r.kind AS kind",
+            uid=user_id,
+        )).records
+        for r in wiki_rows:
+            nodes[r["aid"]] = {
+                "id": r["aid"], "label": r["atitle"] or r["aid"],
+                "node_type": "note",
+            }
+            nodes[r["bid"]] = {
+                "id": r["bid"], "label": r["btitle"] or r["bid"],
+                "node_type": "note",
+            }
+            edges.append({
+                "id": f"wiki:{r['aid']}:{r['bid']}",
+                "source": r["aid"], "target": r["bid"],
+                "kind": "wiki", "relation_type": "wiki",
+            })
~~~

**整体解释：** 画布不只需要实体，还要看见笔记之间的显式引用。WIKI 节点以 note_type 返回，前端已有对应类型和边样式。没有来源过滤时显示双链；查看单个文档子图时不应把全局 WIKI 全部塞入。

### 步骤 5：【运行验证】Chunk 提及与双链

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv run python -m compileall -q app main.py
~~~

创建标题为“基础概念”和“FastAPI 笔记”的两篇笔记，在后者写 `[[基础概念]]`。运行 Worker 后请求 `/api/graph/overview`，应出现两篇 Note 节点和 WIKI 边。查询 Neo4j：

~~~cypher
MATCH (c:Chunk)-[:MENTIONS]->(e:Entity)
RETURN c.source_id, c.chunk_index, e.name
~~~

应看到具体 Chunk 序号，而不是只有 Source 级提及。删除目标笔记或去掉双链后重新处理，旧 WIKI 边应消失。

