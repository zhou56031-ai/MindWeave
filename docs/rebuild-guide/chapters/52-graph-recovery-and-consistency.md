# 第 52 篇：图谱重抽、手工关系显示与任务恢复

## 1. 本篇要接通的真实能力

前面的图谱链路能自动抽取、编辑和显示，但还有三个闭环缺口：前端的“重新抽取”按钮缺接口；手工实体与关系保存后不一定进入 overview 结果；Worker 在 running 状态崩溃会把工单永远留在运行中。本篇补齐这三处，并修正类型编辑不能凭别人的 type_id 意外创建同 ID 节点的问题。任务恢复与持久队列的取舍继续见 [Q21](technology-routes/Q21-persistent-work-queues.md)。

所有图编辑、重抽和恢复仍按当前用户范围处理。重抽返回“已排队”只说明 MySQL 工单提交，不表示 Neo4j 已完成；页面应继续看 extract-logs 和 events。恢复超时 running 采用 30 分钟保守阈值，避免正常模型调用被过早抢走；多 Worker 或超长任务场景以后应增加心跳/租约，不能把时间阈值当严格互斥。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 文件 | 职责 |
|---:|---|---|---|
| 1 | 【修改】 | backend/app/graph/router.py | 当前用户笔记重抽 |
| 2 | 【修改】 | backend/app/graph/views.py | 手工实体与边进入画布 |
| 3 | 【修改】 | backend/app/graph/edit_service.py | 类型 ID 归属、合并手工边 |
| 4 | 【新增文件】 | backend/app/graph/task_recovery.py | 超时运行工单回收 |
| 5 | 【修改】 | backend/app/graph/worker.py | 启动与空闲时恢复 |
| 6 | 【修改】 | backend/app/services/knowledge_service.py | 删除文档后清理提取图片 |
| 7 | 【运行验证】 | 停 Worker、重抽与双账号 | 任务和图状态收敛 |

第 38 篇提取的图片位于按 user_id/md5 分隔的本地目录，单份删除已在第 38 篇清理。本篇补全量清理路径：只有数据库删除已提交，才可以删除对应图片；图库与数据库不是同一事务，进程崩溃留下的孤儿文件需定期扫描。

## 3. 按顺序修改文件与验证

### 步骤 1：【修改】backend/app/graph/router.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/router.py
~~~

**修改定位与前后对照：** 在已有 /notes/{note_id}/related 附近添加 POST 重抽；先用 MySQL 验证笔记归属，再在同一会话登记任务并提交。

~~~diff
 from app.graph.views import entity_detail, entity_sources, graph_view
+from app.graph.task_queue import enqueue_graph
@@
+@graph_router.post("/notes/{note_id}/re-extract")
+async def reextract_note(
+    note_id: str,
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+):
+    owned = await db.scalar(select(Note.id).where(
+        Note.id == note_id, Note.user_id == user_id,
+    ))
+    if owned is None:
+        raise HTTPException(status_code=404, detail="笔记不存在")
+    await enqueue_graph(db, user_id, "note", note_id)
+    await db.commit()
+    return success_response(data={"triggered": True})
+
+
 @graph_router.get("/notes/{note_id}/related")
~~~

**整体解释：** 浏览器只提交 note_id，不提交图任务的 user_id。路由先用 JWT 账号查到这篇笔记，才把工单放入 MySQL；别人猜到 UUID 也无法安排他的内容重抽。已在运行的旧任务被重新置 pending 后，旧 Worker 的 run_token 会失效；新 Worker 会读取最新正文。返回 triggered 是“信件已投进处理箱”，不是“图已经更新”。

### 步骤 2：【修改】backend/app/graph/views.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/views.py
~~~

**修改定位与前后对照：** 在 graph_view 的 for row in rows 循环后纳入手工实体；在 RELATED 边查询后纳入 MANUAL_RELATION。source_kind 指定时不混进全局手工实体。

~~~diff
     for row in rows:
@@
         edges.append({
@@
         })
+    if source_kind is None:
+        manual = (await graph_driver().execute_query(
+            "MATCH (e:Entity {user_id:$uid,manual:true}) "
+            "RETURN e.id AS id,e.name AS name,e.entity_type AS etype "
+            "LIMIT $limit",
+            uid=user_id, limit=limit,
+        )).records
+        for row in manual:
+            nodes[row["id"]] = {
+                "id": row["id"], "label": row["name"],
+                "node_type": "entity", "entity_type_id": row["etype"],
+            }
+            entity_ids.append(row["id"])
     if entity_ids:
@@
         edges.extend({
@@
         } for r in related)
+        manual_edges = (await graph_driver().execute_query(
+            "MATCH (a:Entity {user_id:$uid})-[r:MANUAL_RELATION {user_id:$uid}]->"
+            "(b:Entity {user_id:$uid}) "
+            "WHERE a.id IN $ids AND b.id IN $ids "
+            "RETURN r.id AS id,a.id AS aid,b.id AS bid,"
+            "r.relation_type AS kind LIMIT 300",
+            uid=user_id, ids=list(set(entity_ids)),
+        )).records
+        edges.extend({
+            "id": r["id"], "source": r["aid"], "target": r["bid"],
+            "kind": "relation", "relation_type": r["kind"],
+        } for r in manual_edges)
     return {"nodes": list(nodes.values()), "edges": edges}
~~~

**整体解释：** 第 44 篇把手工边写进图，但第 43 篇只读取自动 RELATED，像仓库已经存了货，橱窗却只摆自动生成的货。本步把手工节点也纳入 overview，保证一对纯手工实体没有来源笔记时仍能显示；手工边仅在两端都属于当前用户且都在这次返回的节点里出现。limit 仍控制画布规模，不应为了显示全部图而让接口无限返回。

### 步骤 3：【修改】backend/app/graph/edit_service.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/edit_service.py
~~~

**修改定位与前后对照：** save_type 不能对前端传来的 type_id 使用 MERGE 创建；创建和更新分开。merge_entities 在删除 source 前把手工出边与入边转给 target。

~~~diff
 async def save_type(user_id: str, payload: TypeIn, type_id: str | None = None) -> dict:
     tid = type_id or str(uuid4())
+    verb = (
+        "MATCH (t:EntityType {id:$id,user_id:$uid}) "
+        if type_id else
+        "CREATE (t:EntityType {id:$id,user_id:$uid}) "
+    )
     rows = (await graph_driver().execute_query(
-        "MERGE (t:EntityType {id:$id,user_id:$uid}) "
+        verb +
         "SET t.name=$name,t.display_name=$display,t.color=$color,t.icon=$icon "
@@
-    return {**one(rows), "is_system": False}
+    return {**one(rows), "is_system": False}
@@ async def merge_entities(
             await tx.run(
                 "MATCH (o:Entity {user_id:$uid})-[r:RELATED]->(s:Entity {id:$sid,user_id:$uid}) "
@@
                 uid=user_id, sid=source_id, tid=target_id,
             )
+            await tx.run(
+                "MATCH (s:Entity {id:$sid,user_id:$uid})-[r:MANUAL_RELATION]->"
+                "(o:Entity {user_id:$uid}) "
+                "MATCH (t:Entity {id:$tid,user_id:$uid}) "
+                "WHERE o.id <> $tid "
+                "WITH t,o,r,r.id AS rid,r.relation_type AS kind "
+                "DELETE r WITH t,o,rid,kind "
+                "CREATE (t)-[:MANUAL_RELATION {id:rid,user_id:$uid,"
+                "relation_type:kind}]->(o)",
+                uid=user_id, sid=source_id, tid=target_id,
+            )
+            await tx.run(
+                "MATCH (o:Entity {user_id:$uid})-[r:MANUAL_RELATION]->"
+                "(s:Entity {id:$sid,user_id:$uid}) "
+                "MATCH (t:Entity {id:$tid,user_id:$uid}) "
+                "WHERE o.id <> $tid "
+                "WITH t,o,r,r.id AS rid,r.relation_type AS kind "
+                "DELETE r WITH t,o,rid,kind "
+                "CREATE (o)-[:MANUAL_RELATION {id:rid,user_id:$uid,"
+                "relation_type:kind}]->(t)",
+                uid=user_id, sid=source_id, tid=target_id,
+            )
             await tx.run(
                 "MATCH (s:Entity {id:$sid,user_id:$uid}) DETACH DELETE s",
~~~

**整体解释：** 更新别人类型 ID 时，MATCH 找不到就返回 404，不能把“没找到”误当成“替他创建一个同 ID 类型”。合并两实体时，手工关系和自动关系都要迁移；源实体原本与目标直接相连的边不迁移成自环，其余边保留原 id 和类型，让前端能继续按关系 ID 删除。图事务失败会整体回滚，避免留下半合并状态。若用户确实需要自环，应设计独立规则，而不是合并时意外制造。

### 步骤 4：【新增文件】backend/app/graph/task_recovery.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/task_recovery.py
~~~

**完整文件内容：**

~~~python
"""把超时 running 工单重新放回可处理队列。"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.db_config import AsyncSessionLocal
from app.models.graph_task import GraphTask

STALE_AFTER = timedelta(minutes=30)


async def recover_stale() -> int:
    cutoff = datetime.now(UTC).replace(tzinfo=None) - STALE_AFTER
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(GraphTask).where(
                GraphTask.status == "running",
                GraphTask.updated_at < cutoff,
            ).with_for_update(skip_locked=True)
        )).scalars().all()
        for row in rows:
            row.status = "pending" if row.attempts < 3 else "failed"
            row.run_token = None
            row.error_message = "Worker 超时，已回收" if row.status == "pending" else "重试次数耗尽"
        await db.commit()
        return len(rows)
~~~

**整体解释：** running 只说明“某个 Worker 曾经领过”，不证明进程现在还活着。超过阈值才回收，避免正常调用被重复接管。回收会清掉旧 run_token；旧 Worker 若后来醒来，其完成状态不能再覆盖新任务。这里仍是至少一次处理的任务语义：Neo4j 的 replace_source 必须按来源幂等，不能把每次重试都累加一份节点。

### 步骤 5：【修改】backend/app/graph/worker.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/worker.py
~~~

**修改定位与前后对照：** 启动后和每次空闲时调用回收；不要在每条任务执行中重置状态。

~~~diff
 from app.graph.neo4j_client import close_graph_driver, ensure_graph_schema
+from app.graph.task_recovery import recover_stale
@@ async def main() -> None:
     await init_db()
     await ensure_graph_schema()
+    await recover_stale()
     try:
         while True:
             if not await process_one():
+                await recover_stale()
                 await asyncio.sleep(2)
~~~

**整体解释：** Worker 启动时先捡起上次崩溃留下的过期工单；运行时只有队列空了才继续扫描，既能恢复也不会让扫描压过正常任务。30 分钟以内的 running 会保持原状，以免刚才只是慢调用。恢复后 task.attempts 不清零，第三次失败要进入 failed，让管理员知道需要修原因。

### 步骤 6：【修改】backend/app/services/knowledge_service.py

**编辑文件的完整地址：**

~~~text
./backend/app/services/knowledge_service.py
~~~

**修改定位与前后对照：** 第 38 篇已给 delete_document 加单份图片清理；这里只给 clean_all 保存 md5 列表，MySQL commit 成功后再删图片。remove_images 已在第 38 篇导入，无需重复写 import。

~~~diff
@@ async def clean_all(
-    result = await db.execute(select(KnowledgeDocument.id).where(
+    result = await db.execute(select(KnowledgeDocument.id, KnowledgeDocument.md5).where(
         KnowledgeDocument.user_id == user_id
     ))
-    ids = list(result.scalars().all())
+    rows = result.all()
+    ids = [row.id for row in rows]
@@
     await db.commit()
+    for row in rows:
+        remove_images(user_id, row.md5)
     return len(ids)
~~~

**整体解释：** MySQL 删除像撤掉借书记录，本地图片像抽走书架上的附件；不能先抽附件再试提交数据库，否则提交失败时仍有文档却没有图片。clean_all 批量拿到本账号每份文档的 md5，提交后只清这些目录，不碰其他账号。生产部署应把数据目录放持久卷，并定期对照文档表清理孤儿图片；本地练习可先验证一份 PDF 删除后对应目录消失。

### 步骤 7：【运行验证】从按钮到任务状态收敛

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv run python -m compileall -q app main.py
~~~

用两账号分别创建笔记和手工实体。第一账号点击“重新抽取”，应先看到 pending/running，再看到 completed；用第二账号 note_id 请求应是 404。创建两手工实体与关系后，overview 必须同时出现节点和边；合并时边应转移。模拟 Worker 在认领后停止，再把测试工单时间设为阈值以前，重启 Worker 应接回并处理，普通未超时任务不能被抢走。上传一份含图片 PDF，删除后确认该用户该 md5 图片目录被清理，另一账号目录保持原样。
