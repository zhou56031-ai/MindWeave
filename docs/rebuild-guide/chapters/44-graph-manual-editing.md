# 第 44 篇：图谱实体、类型、关系的人工修订

## 1. 本篇要接通的真实能力

模型抽取会把同义词拆开，也会写错实体描述。参考项目的图谱页面允许人工创建、编辑、删除、合并实体与类型，并维护关系。本篇给出有用户范围的手工编辑服务；手工动作与自动来源边区分开，删除一个自动抽取错误实体后，下次重抽可能再次出现，所以合并和规则修订也要留痕。图谱不因客户端提交 entity_id 就相信其归属。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 文件 | 职责 |
|---:|---|---|---|
| 1 | 【修改】 | backend/app/graph/neo4j_client.py | 类型名和手工关系 ID 约束 |
| 2 | 【新增文件】 | backend/app/graph/edit_schemas.py | 编辑输入边界 |
| 3 | 【新增文件】 | backend/app/graph/edit_service.py | 用户范围图修改 |
| 4 | 【修改】 | backend/app/graph/router.py | 挂接图编辑接口 |

前端仍使用已复制源码，本篇只写后端。所有编辑接口都应有 JWT；批量合并时事务必须完整完成才返回成功。

## 3. 按顺序修改文件与验证

### 步骤 1：【修改】backend/app/graph/neo4j_client.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/neo4j_client.py
~~~

**修改定位与前后对照：** statements 增加两项。

~~~diff
     statements = [
+        "CREATE CONSTRAINT entity_type_user_name IF NOT EXISTS FOR (t:EntityType) REQUIRE (t.user_id, t.name) IS UNIQUE",
+        "CREATE CONSTRAINT manual_relation_id IF NOT EXISTS FOR ()-[r:MANUAL_RELATION]-() REQUIRE r.id IS UNIQUE",
~~~

**整体解释：** 图类型像画布节点的颜色词典，同一用户不能登记两个相同名称；手工关系有独立 ID 才能精准删除，不靠“两个端点相同”误删不同关系。约束是并发保险，服务仍须提前给出可理解的冲突错误。

### 步骤 2：【新增文件】backend/app/graph/edit_schemas.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/edit_schemas.py
~~~

**完整文件内容：**

~~~python
"""图编辑请求不接受客户端 user_id。"""
from pydantic import BaseModel, Field


class EntityIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    display_name: str | None = Field(default=None, max_length=120)
    type_id: str | None = None
    description: str | None = Field(default=None, max_length=500)
    aliases: list[str] = Field(default_factory=list, max_length=20)


class TypeIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    display_name: str = Field(min_length=1, max_length=50)
    color: str = Field(default="#888888", pattern=r"^#[0-9a-fA-F]{6}$")
    icon: str | None = Field(default=None, max_length=100)


class RelationIn(BaseModel):
    source_id: str
    target_id: str
    relation_type: str = Field(min_length=1, max_length=50)


class MergeIn(BaseModel):
    target_id: str
    source_id: str
~~~

**整体解释：** 编辑表单可以决定名称和颜色，不能决定数据归属。类型长度、颜色格式和关系名称先在 HTTP 边界检查；关系两端是否属于当前用户还得由图查询判断，Pydantic 只看得到请求体，不能代替授权。

### 步骤 3：【新增文件】backend/app/graph/edit_service.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/edit_service.py
~~~

**完整文件内容：**

~~~python
"""仅在当前用户子图里执行人工编辑。"""
from uuid import uuid4

from fastapi import HTTPException

from app.graph.edit_schemas import EntityIn, RelationIn, TypeIn
from app.graph.neo4j_client import graph_driver


def one(records, message="图对象不存在"):
    if not records:
        raise HTTPException(status_code=404, detail=message)
    return records[0].data()


async def create_entity(user_id: str, payload: EntityIn) -> dict:
    eid = str(uuid4())
    rows = (await graph_driver().execute_query(
        "CREATE (e:Entity {id:$id,user_id:$uid,name:$name,display_name:$display,"
        "entity_type:$etype,description:$description,aliases:$aliases,manual:true}) "
        "RETURN e.id AS id,e.name AS name,e.display_name AS display_name,"
        "e.entity_type AS type_id,e.description AS description,e.aliases AS aliases",
        id=eid, uid=user_id, name=payload.name.strip(),
        display=payload.display_name or payload.name.strip(),
        etype=payload.type_id, description=payload.description or "",
        aliases=payload.aliases,
    )).records
    return {**one(rows), "confidence": 1.0, "source_note_ids": []}


async def update_entity(user_id: str, entity_id: str, payload: EntityIn) -> dict:
    rows = (await graph_driver().execute_query(
        "MATCH (e:Entity {id:$id,user_id:$uid}) "
        "SET e.display_name=$display,e.entity_type=$etype,"
        "e.description=$description,e.aliases=$aliases "
        "RETURN e.id AS id,e.name AS name,e.display_name AS display_name,"
        "e.entity_type AS type_id,e.description AS description,e.aliases AS aliases",
        id=entity_id, uid=user_id, display=payload.display_name or payload.name,
        etype=payload.type_id, description=payload.description or "",
        aliases=payload.aliases,
    )).records
    return {**one(rows), "confidence": 1.0, "source_note_ids": []}


async def delete_entity(user_id: str, entity_id: str) -> None:
    rows = (await graph_driver().execute_query(
        "MATCH (e:Entity {id:$id,user_id:$uid}) "
        "WITH e,e.id AS found DETACH DELETE e RETURN found",
        id=entity_id, uid=user_id,
    )).records
    one(rows)


async def merge_entities(user_id: str, target_id: str, source_id: str) -> dict:
    if target_id == source_id:
        raise HTTPException(status_code=422, detail="不能合并同一实体")
    driver = graph_driver()
    async with driver.session() as session:
        async with await session.begin_transaction() as tx:
            result = await tx.run(
                "MATCH (t:Entity {id:$tid,user_id:$uid}),"
                "(s:Entity {id:$sid,user_id:$uid}) RETURN t.id AS tid",
                tid=target_id, sid=source_id, uid=user_id,
            )
            rows = await result.data()
            one(rows)
            await tx.run(
                "MATCH (n:Source {user_id:$uid})-[m:MENTIONS]->"
                "(s:Entity {id:$sid,user_id:$uid}) "
                "MATCH (t:Entity {id:$tid,user_id:$uid}) "
                "MERGE (n)-[:MENTIONS]->(t) DELETE m",
                uid=user_id, sid=source_id, tid=target_id,
            )
            await tx.run(
                "MATCH (s:Entity {id:$sid,user_id:$uid})-[r:RELATED]->(o:Entity {user_id:$uid}) "
                "MATCH (t:Entity {id:$tid,user_id:$uid}) "
                "WHERE o.id <> $tid "
                "MERGE (t)-[:RELATED {user_id:$uid,source_kind:r.source_kind,"
                "source_id:r.source_id,relation_type:r.relation_type}]->(o) DELETE r",
                uid=user_id, sid=source_id, tid=target_id,
            )
            await tx.run(
                "MATCH (o:Entity {user_id:$uid})-[r:RELATED]->(s:Entity {id:$sid,user_id:$uid}) "
                "MATCH (t:Entity {id:$tid,user_id:$uid}) "
                "WHERE o.id <> $tid "
                "MERGE (o)-[:RELATED {user_id:$uid,source_kind:r.source_kind,"
                "source_id:r.source_id,relation_type:r.relation_type}]->(t) DELETE r",
                uid=user_id, sid=source_id, tid=target_id,
            )
            await tx.run(
                "MATCH (s:Entity {id:$sid,user_id:$uid})-[r:MANUAL_RELATION]->"
                "(o:Entity {user_id:$uid}) MATCH (t:Entity {id:$tid,user_id:$uid}) "
                "WHERE o.id <> $tid CREATE (t)-[nr:MANUAL_RELATION {id:randomUUID(),"
                "user_id:$uid,relation_type:r.relation_type}]->(o) DELETE r",
                uid=user_id, sid=source_id, tid=target_id,
            )
            await tx.run(
                "MATCH (o:Entity {user_id:$uid})-[r:MANUAL_RELATION]->"
                "(s:Entity {id:$sid,user_id:$uid}) MATCH (t:Entity {id:$tid,user_id:$uid}) "
                "WHERE o.id <> $tid CREATE (o)-[nr:MANUAL_RELATION {id:randomUUID(),"
                "user_id:$uid,relation_type:r.relation_type}]->(t) DELETE r",
                uid=user_id, sid=source_id, tid=target_id,
            )
            await tx.run(
                "MATCH (s:Entity {id:$sid,user_id:$uid}) DETACH DELETE s",
                uid=user_id, sid=source_id,
            )
            await tx.commit()
    rows = (await driver.execute_query(
        "MATCH (e:Entity {id:$id,user_id:$uid}) "
        "RETURN e.id AS id,e.name AS name,e.display_name AS display_name,"
        "e.entity_type AS type_id,e.description AS description,e.aliases AS aliases",
        id=target_id, uid=user_id,
    )).records
    return {**one(rows), "confidence": 1.0, "source_note_ids": []}


async def list_types(user_id: str) -> list[dict]:
    rows = (await graph_driver().execute_query(
        "MATCH (t:EntityType {user_id:$uid}) "
        "RETURN t.id AS id,t.user_id AS user_id,t.name AS name,"
        "t.display_name AS display_name,t.color AS color,t.icon AS icon "
        "ORDER BY name", uid=user_id,
    )).records
    return [{**row.data(), "is_system": False} for row in rows]


async def save_type(user_id: str, payload: TypeIn, type_id: str | None = None) -> dict:
    tid = type_id or str(uuid4())
    driver = graph_driver()
    if type_id is not None:
        owned = (await driver.execute_query(
            "MATCH (t:EntityType {id:$id,user_id:$uid}) RETURN t.id AS id",
            id=type_id, uid=user_id,
        )).records
        if not owned:
            raise HTTPException(status_code=404, detail="类型不存在")
    rows = (await graph_driver().execute_query(
        "MERGE (t:EntityType {id:$id,user_id:$uid}) "
        "SET t.name=$name,t.display_name=$display,t.color=$color,t.icon=$icon "
        "RETURN t.id AS id,t.user_id AS user_id,t.name AS name,"
        "t.display_name AS display_name,t.color AS color,t.icon AS icon",
        id=tid, uid=user_id, name=payload.name,
        display=payload.display_name, color=payload.color, icon=payload.icon,
    )).records
    return {**one(rows), "is_system": False}


async def delete_type(user_id: str, type_id: str) -> None:
    rows = (await graph_driver().execute_query(
        "MATCH (t:EntityType {id:$id,user_id:$uid}) "
        "WITH t,t.id AS found DELETE t RETURN found",
        id=type_id, uid=user_id,
    )).records
    one(rows)


async def create_relation(user_id: str, payload: RelationIn) -> dict:
    rid = str(uuid4())
    rows = (await graph_driver().execute_query(
        "MATCH (a:Entity {id:$aid,user_id:$uid}),"
        "(b:Entity {id:$bid,user_id:$uid}) "
        "CREATE (a)-[r:MANUAL_RELATION {id:$rid,user_id:$uid,"
        "relation_type:$rtype}]->(b) RETURN r.id AS id",
        aid=payload.source_id, bid=payload.target_id, uid=user_id,
        rid=rid, rtype=payload.relation_type,
    )).records
    one(rows, "关系端点不存在")
    return {"id": rid, "user_id": user_id, "source_id": payload.source_id,
            "target_id": payload.target_id, "relation_type": payload.relation_type,
            "properties": {}, "confidence": 1.0}


async def delete_relation(user_id: str, relation_id: str) -> None:
    rows = (await graph_driver().execute_query(
        "MATCH ()-[r:MANUAL_RELATION {id:$id,user_id:$uid}]->() "
        "WITH r,r.id AS found DELETE r RETURN found",
        id=relation_id, uid=user_id,
    )).records
    one(rows)
~~~

**整体解释：** 手工实体使用随机 ID，和第 41 篇按名称生成的自动实体不同；人改的是展示名、类型、说明和别名，不直接改变用于自动合并的规范名。合并需要在一个图事务里转移提及和关系，再删除源实体，不能先删后补。所有 MATCH 都要求当前用户 ID；对不存在或别人的 ID 统一 404。手工类型目前按用户保存，参考项目的系统预置类型要在需要时另行种入。

### 步骤 4：【修改】backend/app/graph/router.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/router.py
~~~

**修改定位与前后对照：** 添加服务导入和各 HTTP 入口；实际粘贴时保持 /entity/{entity_id} 与 /entities/{entity_id} 区分。

~~~diff
+from app.graph.edit_schemas import EntityIn, TypeIn, RelationIn, MergeIn
+from app.graph import edit_service as edits
@@
 graph_router = APIRouter(prefix="/api/graph", tags=["graph"])
+
+@graph_router.post("/entities")
+async def create_entity(payload: EntityIn, uid: str = Depends(get_current_user_id)):
+    return success_response(data=await edits.create_entity(uid, payload))
+
+@graph_router.put("/entities/{entity_id}")
+async def update_entity(entity_id: str, payload: EntityIn,
+                        uid: str = Depends(get_current_user_id)):
+    return success_response(data=await edits.update_entity(uid, entity_id, payload))
+
+@graph_router.delete("/entities/{entity_id}")
+async def delete_entity(entity_id: str, uid: str = Depends(get_current_user_id)):
+    await edits.delete_entity(uid, entity_id)
+    return success_response(message="实体已删除")
+
+@graph_router.post("/entities/merge")
+async def merge_entity(payload: MergeIn, uid: str = Depends(get_current_user_id)):
+    return success_response(data=await edits.merge_entities(
+        uid, payload.target_id, payload.source_id))
+
+@graph_router.get("/types")
+async def types(uid: str = Depends(get_current_user_id)):
+    return success_response(data=await edits.list_types(uid))
+
+@graph_router.post("/types")
+async def create_type(payload: TypeIn, uid: str = Depends(get_current_user_id)):
+    return success_response(data=await edits.save_type(uid, payload))
+
+@graph_router.put("/types/{type_id}")
+async def update_type(type_id: str, payload: TypeIn,
+                      uid: str = Depends(get_current_user_id)):
+    return success_response(data=await edits.save_type(uid, payload, type_id))
+
+@graph_router.delete("/types/{type_id}")
+async def remove_type(type_id: str, uid: str = Depends(get_current_user_id)):
+    await edits.delete_type(uid, type_id)
+    return success_response(message="类型已删除")
+
+@graph_router.post("/relations")
+async def create_relation(payload: RelationIn, uid: str = Depends(get_current_user_id)):
+    return success_response(data=await edits.create_relation(uid, payload))
+
+@graph_router.delete("/relations/{relation_id}")
+async def delete_relation(relation_id: str, uid: str = Depends(get_current_user_id)):
+    await edits.delete_relation(uid, relation_id)
+    return success_response(message="关系已删除")
~~~

**整体解释：** 路由只是把已认证用户和校验后的表单交给服务，不在这里拼 Cypher。前端编辑完再拉 overview；若返回 200 但画布未变，应核对视图服务是否把 MANUAL_RELATION 加入边集合。新增或删除操作必须真正落图后再给成功响应。

### 步骤 5：【运行验证】双账号修订

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv run python -m compileall -q app main.py
~~~

两个账号分别建同名手工实体；互换 entity_id 做详情、修改、删除，应只得到本人结果或 404。对同账号两个临时实体执行关系创建、合并与删除，确认没有残留指向已删除实体的边。测试后清理临时实体和类型，勿对真实图执行全量 DETACH DELETE。
