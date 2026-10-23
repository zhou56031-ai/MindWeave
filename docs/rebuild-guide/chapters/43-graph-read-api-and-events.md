# 第 43 篇：图谱画布、来源查询与构建状态

## 1. 本篇要接通的真实能力

第 42 篇的 Worker 能写图，但复制来的 GraphPage 还没有 /api/graph/overview、关联来源和构建状态。此篇按前端 GraphView 结构提供节点与边：实体、笔记、文档节点均带当前用户范围；实体邻居和来源查询不能仅凭可猜测的 entity_id 直接读别人的图。extract-logs 映射 MySQL GraphTask 状态；events 用已登录的 fetch/SSE 定期通知页面刷新。图谱展示结构与参考项目一致，底层 Source 节点设计是复刻过程的简化。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 文件 | 职责 |
|---:|---|---|---|
| 1 | 【新增文件】 | backend/app/graph/views.py | 图查询转前端 GraphView |
| 2 | 【新增文件】 | backend/app/graph/router.py | 只读图、任务状态与 SSE |
| 3 | 【修改】 | backend/main.py | 注册 /api/graph |
| 4 | 【运行验证】 | 当前用户临时图 | 节点、边、越权和状态 |

本篇不允许把客户端传入的 Cypher、标签名或任意排序字段拼进查询。浏览器数据只用于参数值。

## 3. 按顺序修改文件与验证

### 步骤 1：【新增文件】backend/app/graph/views.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/views.py
~~~

**完整文件内容：**

~~~python
"""把用户范围内的图记录转换成前端 GraphView。"""
from app.graph.neo4j_client import graph_driver


async def graph_view(
    user_id: str, *, source_kind: str | None = None,
    source_id: str | None = None, limit: int = 50,
) -> dict:
    if source_kind is not None and source_kind not in {"note", "doc"}:
        raise ValueError("来源类型不支持")
    query = (
        "MATCH (s:Source {user_id:$uid})-[:MENTIONS]->(e:Entity {user_id:$uid}) "
        "WHERE ($kind IS NULL OR s.kind=$kind) AND ($sid IS NULL OR s.id=$sid) "
        "RETURN s.id AS sid,s.kind AS kind,s.title AS title,"
        "e.id AS eid,e.name AS name,e.entity_type AS etype LIMIT $limit"
    )
    rows = (await graph_driver().execute_query(
        query, uid=user_id, kind=source_kind, sid=source_id, limit=limit
    )).records
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    entity_ids = []
    for row in rows:
        nodes[row["sid"]] = {
            "id": row["sid"], "label": row["title"] or row["sid"],
            "node_type": row["kind"],
        }
        nodes[row["eid"]] = {
            "id": row["eid"], "label": row["name"],
            "node_type": "entity", "entity_type_id": row["etype"],
        }
        entity_ids.append(row["eid"])
        edges.append({
            "id": "mention:" + row["sid"] + ":" + row["eid"],
            "source": row["sid"], "target": row["eid"],
            "kind": "relation", "relation_type": "mentions",
        })
    if entity_ids:
        related = (await graph_driver().execute_query(
            "MATCH (a:Entity {user_id:$uid})-[r:RELATED {user_id:$uid}]->"
            "(b:Entity {user_id:$uid}) "
            "WHERE a.id IN $ids AND b.id IN $ids "
            "RETURN a.id AS aid,b.id AS bid,r.relation_type AS kind,"
            "r.source_id AS source_id LIMIT 300",
            uid=user_id, ids=list(set(entity_ids)),
        )).records
        edges.extend({
            "id": "relation:" + r["aid"] + ":" + r["bid"] + ":" + r["source_id"],
            "source": r["aid"], "target": r["bid"],
            "kind": "relation", "relation_type": r["kind"],
        } for r in related)
    return {"nodes": list(nodes.values()), "edges": edges}


async def entity_detail(user_id: str, entity_id: str) -> dict | None:
    rows = (await graph_driver().execute_query(
        "MATCH (e:Entity {user_id:$uid,id:$eid}) "
        "RETURN e.id AS id,e.name AS name,e.entity_type AS etype,"
        "e.description AS description",
        uid=user_id, eid=entity_id,
    )).records
    if not rows:
        return None
    row = rows[0]
    return {
        "id": row["id"], "name": row["name"], "display_name": row["name"],
        "type_id": row["etype"], "description": row["description"],
        "aliases": [], "confidence": 0.0, "source_note_ids": [],
    }


async def entity_sources(user_id: str, entity_id: str) -> list[dict]:
    rows = (await graph_driver().execute_query(
        "MATCH (s:Source {user_id:$uid})-[:MENTIONS]->"
        "(e:Entity {user_id:$uid,id:$eid}) "
        "RETURN s.id AS sid,s.kind AS kind,s.title AS title",
        uid=user_id, eid=entity_id,
    )).records
    return [{
        "entity_id": entity_id, "note_id": row["sid"],
        "source_type": row["kind"], "source_name": row["title"],
        "mention_count": 1, "context": [],
    } for row in rows]
~~~

**整体解释：** 图数据库返回的是节点记录，画布需要 nodes/edges 两个数组。服务先用用户 ID 查 Source→Entity，再只在这批实体 ID 内找同用户 RELATED；相同 ID 的节点通过字典去重。前端拿到来源 ID 后仍需走已鉴权的笔记或文档详情接口，图中的标题不是权限凭据。实体详情和来源查询即使拿到别人的 UUID 也只会返回空。

### 步骤 2：【新增文件】backend/app/graph/router.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/router.py
~~~

**完整文件内容：**

~~~python
"""前端图谱画布的只读 HTTP 与进度事件。"""
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.success_response import success_response
from app.db.db_config import AsyncSessionLocal, get_db
from app.graph.neo4j_client import graph_driver
from app.graph.views import entity_detail, entity_sources, graph_view
from app.models.graph_task import GraphTask
from app.models.note import Note
from app.utils.auth_utils import get_current_user_id

graph_router = APIRouter(prefix="/api/graph", tags=["graph"])


@graph_router.get("/overview")
async def overview(
    limit: int = Query(50, ge=1, le=200),
    user_id: str = Depends(get_current_user_id),
):
    return success_response(data=await graph_view(user_id, limit=limit))


@graph_router.get("/entity/{entity_id}")
async def entity(entity_id: str, user_id: str = Depends(get_current_user_id)):
    return success_response(data=await entity_detail(user_id, entity_id))


@graph_router.get("/entity/{entity_id}/neighbors")
async def neighbors(
    entity_id: str, depth: int = Query(1, ge=1, le=3),
    user_id: str = Depends(get_current_user_id),
):
    if await entity_detail(user_id, entity_id) is None:
        raise HTTPException(status_code=404, detail="实体不存在")
    # depth 已被限定为 1..3；只把固定整数放进 Cypher 路径长度。
    rows = (await graph_driver().execute_query(
        f"MATCH p=(e:Entity {{user_id:$uid,id:$eid}})-[:RELATED*1..{depth}]-(other:Entity) "
        "WHERE all(n IN nodes(p) WHERE n.user_id=$uid) "
        "RETURN DISTINCT other.id AS id LIMIT 50",
        uid=user_id, eid=entity_id,
    )).records
    ids = [entity_id] + [r["id"] for r in rows]
    # 画布只展示含这些实体的已归属来源。
    view = await graph_view(user_id, limit=200)
    view["nodes"] = [n for n in view["nodes"] if n["node_type"] != "entity" or n["id"] in ids]
    allowed = {n["id"] for n in view["nodes"]}
    view["edges"] = [e for e in view["edges"] if e["source"] in allowed and e["target"] in allowed]
    return success_response(data=view)


@graph_router.get("/entity/{entity_id}/notes")
async def sources(entity_id: str, user_id: str = Depends(get_current_user_id)):
    return success_response(data=await entity_sources(user_id, entity_id))


@graph_router.get("/notes/{note_id}/related")
async def note_related(note_id: str, user_id: str = Depends(get_current_user_id)):
    return success_response(data=await graph_view(
        user_id, source_kind="note", source_id=note_id, limit=200,
    ))


@graph_router.get("/docs/{doc_id}/related")
async def doc_related(doc_id: str, user_id: str = Depends(get_current_user_id)):
    return success_response(data=await graph_view(
        user_id, source_kind="doc", source_id=doc_id, limit=200,
    ))


@graph_router.get("/search")
async def search(
    q: str = Query(min_length=1, max_length=100),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    rows = (await graph_driver().execute_query(
        "MATCH (e:Entity {user_id:$uid}) WHERE toLower(e.name) CONTAINS toLower($q) "
        "RETURN e.id AS id,e.name AS name,e.entity_type AS type_id LIMIT 10",
        uid=user_id, q=q,
    )).records
    notes = (await db.execute(select(Note).where(
        Note.user_id == user_id, Note.title.contains(q, autoescape=True)
    ).limit(10))).scalars().all()
    return success_response(data={
        "entities": [dict(row) for row in rows],
        "notes": [{"id": n.id, "title": n.title} for n in notes],
    })


@graph_router.get("/extract-logs")
async def extract_logs(
    note_id: str | None = None,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(GraphTask).where(GraphTask.user_id == user_id)
    if note_id:
        stmt = stmt.where(GraphTask.source_id == note_id)
    rows = (await db.execute(stmt.order_by(GraphTask.updated_at.desc()).limit(50))).scalars()
    return success_response(data=[{
        "note_id": r.source_id, "source_type": r.source_kind,
        "content_hash": "", "status": "success" if r.status == "completed" else r.status,
        "new_count": 0, "update_count": 0, "error_message": r.error_message,
    } for r in rows])


@graph_router.get("/events")
async def events(user_id: str = Depends(get_current_user_id)):
    async def stream():
        previous = {}
        while True:
            async with AsyncSessionLocal() as db:
                rows = (await db.execute(select(GraphTask).where(
                    GraphTask.user_id == user_id
                ).order_by(GraphTask.updated_at.desc()).limit(50))).scalars().all()
                for task in rows:
                    marker = (task.status, task.updated_at)
                    if previous.get(task.id) == marker:
                        continue
                    previous[task.id] = marker
                    kind = "extract_done" if task.status == "completed" else (
                        "extract_failed" if task.status == "failed" else "ping")
                    payload = {"type": kind, "note_id": task.source_id,
                               "source_type": task.source_kind, "status": task.status}
                    yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
            await asyncio.sleep(2)
    return StreamingResponse(stream(), media_type="text/event-stream")
~~~

**整体解释：** 路由只把 JWT 用户交给图查询和任务查询，不能接受请求体自称的 user_id。事件流每轮只查当前用户 50 个最近工单，连接断开会结束生成器。GraphPage 拿到 extract_done 后刷新画布；这不是“所有图节点立即一致”的承诺，Worker 必须先提交图再把工单标为 completed。图故障应由统一异常处理转换成 503，不能把 Neo4j 连接详情回给浏览器。

### 步骤 3：【修改】backend/main.py

**编辑文件的完整地址：**

~~~text
./backend/main.py
~~~

**修改定位与前后对照：**

~~~diff
+from app.graph.router import graph_router
@@
 app.include_router(chat_router)
+app.include_router(graph_router)
~~~

**整体解释：** 前面的路由文件只是写了接待规则；main.py include_router 才把 /api/graph 挂进当前 FastAPI。注册不会立即查询 Neo4j，真正请求到达时才鉴权并读图。

### 步骤 4：【运行验证】页面契约与隔离

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv run python -m compileall -q app main.py
~~~

用两个临时账号分别建立同名实体，/api/graph/overview 只能见各自的 Source/Entity；把另一个账号的 entity_id 放进详情与来源路径应得到 null 或空列表。用 GraphPage 验证节点字段为 id/label/node_type、边字段为 id/source/target/kind。若某类画布节点暂时没显示，先核对 Worker 是否 completed，再核对 Neo4j 的 MENTIONS，不要直接在前端造假节点。
