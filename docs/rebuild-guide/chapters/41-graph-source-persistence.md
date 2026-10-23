# 第 41 篇：把来源、实体和关系写入 Neo4j

## 1. 本篇要接通的真实能力

第 40 篇给出已校验的实体关系草稿。本篇让同一用户的笔记或文档成为图谱的来源节点，按稳定实体 ID 合并同名实体，建立 MENTIONS 与 RELATED 边。更新同一来源时替换它的旧边；删除来源时只清理该来源的图边，不误删其他来源共享的实体。用户隔离不仅在路由，也在每条 Cypher 的 uid 条件里。此篇先给存储能力，第 42 篇再接后台任务。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 文件 | 职责 |
|---:|---|---|---|
| 1 | 【修改】 | backend/app/graph/neo4j_client.py | 增加 Source 与关系索引 |
| 2 | 【新增文件】 | backend/app/graph/graph_store.py | 单事务替换来源图 |
| 3 | 【运行验证】 | Neo4j 临时数据 | 双用户同名实体仍分开 |

这里的 Source 同时对应参考项目里的 Note/Doc 来源语义；展示层在第 43 篇把 kind 映射为 note/doc。它减少本阶段重复 Cypher，后续向量 Chunk 仍用独立节点。

## 3. 按顺序修改文件与验证

### 步骤 1：【修改】backend/app/graph/neo4j_client.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/neo4j_client.py
~~~

**修改定位与前后对照：** 在 ensure_graph_schema 的 statements 内补 Source 约束和关系查询索引。

~~~diff
     statements = [
+        "CREATE CONSTRAINT source_user_kind_id IF NOT EXISTS FOR (s:Source) REQUIRE (s.user_id, s.kind, s.id) IS UNIQUE",
         "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
@@
         "CREATE INDEX entity_user IF NOT EXISTS FOR (e:Entity) ON (e.user_id)",
+        "CREATE INDEX source_user IF NOT EXISTS FOR (s:Source) ON (s.user_id)",
~~~

**整体解释：** Source 像每张抽取结果的封面，复合键说明“同一用户、同一种来源、同一个 ID”才是一份资料。不同用户即使导入相同 MD5，也不共享封面。约束保证并发写入时不会出现两张相同封面；业务查询仍必须显式带 user_id。

### 步骤 2：【新增文件】backend/app/graph/graph_store.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/graph_store.py
~~~

**完整文件内容：**

~~~python
"""按用户和来源替换图谱边；单次写入使用一个 Neo4j 事务。"""
from uuid import NAMESPACE_URL, uuid5

from app.graph.neo4j_client import graph_driver
from app.graph.schemas import ExtractResult


def entity_id(user_id: str, name: str) -> str:
    return str(uuid5(NAMESPACE_URL, user_id + ":" + name.strip().casefold()))


async def replace_source(
    user_id: str, kind: str, source_id: str, title: str, result: ExtractResult
) -> None:
    if kind not in {"note", "doc"}:
        raise ValueError("来源类型不支持")
    driver = graph_driver()
    async with driver.session() as session:
        async with await session.begin_transaction() as tx:
            await tx.run(
                "MERGE (s:Source {user_id:$uid,kind:$kind,id:$sid}) "
                "SET s.title=$title",
                uid=user_id, kind=kind, sid=source_id, title=title[:255],
            )
            await tx.run(
                "MATCH (s:Source {user_id:$uid,kind:$kind,id:$sid})-[r:MENTIONS]->() DELETE r",
                uid=user_id, kind=kind, sid=source_id,
            )
            await tx.run(
                "MATCH ()-[r:RELATED {user_id:$uid,source_kind:$kind,source_id:$sid}]->() DELETE r",
                uid=user_id, kind=kind, sid=source_id,
            )
            for item in result.entities:
                eid = entity_id(user_id, item.name)
                await tx.run(
                    "MERGE (e:Entity {id:$eid}) "
                    "SET e.user_id=$uid, e.name=$name, e.entity_type=$etype, "
                    "e.description=$description "
                    "WITH e MATCH (s:Source {user_id:$uid,kind:$kind,id:$sid}) "
                    "MERGE (s)-[:MENTIONS]->(e)",
                    eid=eid, uid=user_id, name=item.name.strip(),
                    etype=item.type, description=item.description,
                    kind=kind, sid=source_id,
                )
            for link in result.relations:
                await tx.run(
                    "MATCH (a:Entity {id:$source_eid,user_id:$uid}) "
                    "MATCH (b:Entity {id:$target_eid,user_id:$uid}) "
                    "MERGE (a)-[r:RELATED {user_id:$uid,source_kind:$kind,"
                    "source_id:$sid,relation_type:$rtype}]->(b)",
                    source_eid=entity_id(user_id, link.source),
                    target_eid=entity_id(user_id, link.target),
                    uid=user_id, kind=kind, sid=source_id,
                    rtype=link.relation_type,
                )
            await tx.commit()


async def delete_source(user_id: str, kind: str, source_id: str) -> None:
    if kind not in {"note", "doc"}:
        raise ValueError("来源类型不支持")
    driver = graph_driver()
    async with driver.session() as session:
        async with await session.begin_transaction() as tx:
            await tx.run(
                "MATCH ()-[r:RELATED {user_id:$uid,source_kind:$kind,source_id:$sid}]->() DELETE r",
                uid=user_id, kind=kind, sid=source_id,
            )
            await tx.run(
                "MATCH (s:Source {user_id:$uid,kind:$kind,id:$sid}) DETACH DELETE s",
                uid=user_id, kind=kind, sid=source_id,
            )
            await tx.commit()
~~~

**整体解释：** 可以把一个来源当成一位证人：更新这位证人的证词，要撤掉**它自己**旧的 MENTIONS/RELATED，再放入新证词，不能把别的证人的共同实体一并抹掉。稳定实体 ID 由用户 ID 与规范名决定；同名跨用户不会合并。整次图更新在一个 Neo4j 事务内，失败时不会出现“删完旧边但新边只写一半”。它仍不能与 MySQL 的笔记提交合成一个跨库事务，所以第 42 篇需要任务状态和重试。

### 步骤 3：【运行验证】替换与隔离

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv run python -m compileall -q app main.py
~~~

用临时 user_id、source_id 构造 ExtractResult，调用 replace_source 两次：第二次换一条关系后，旧来源边应消失；另一个 user_id 用同名实体仍得到不同 entity_id。最后只对临时来源调用 delete_source。不要使用真实用户图数据做破坏性演练。
