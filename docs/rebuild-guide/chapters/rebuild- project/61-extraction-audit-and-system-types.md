# 第 61 篇：抽取日志、内容哈希、孤儿清理与系统类型

## 1. 本篇要接通的真实能力

复刻项目的 GraphTask 只保存来源和状态，无法区分“内容没变所以跳过”“手动强制重抽”和“这次新增了多少实体”。参考项目另有 `graph_extract_logs`、内容哈希、payload、force、孤儿实体清扫和系统预置类型。本篇补全这张可审计的图构建账本。技术路线见 [Q21](technology-routes/Q21-persistent-work-queues.md) 与 [Q19](technology-routes/Q19-neo4j-graph-store.md)。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 文件 | 职责 |
|---:|---|---|---|
| 1 | 【新增文件】 | backend/app/models/graph_extract_log.py | 每次来源抽取审计 |
| 2 | 【修改】 | backend/app/models/graph_task.py | 内容哈希、标题、payload、force |
| 3 | 【修改】 | backend/app/db/db_config.py | 注册日志表 |
| 4 | 【新增文件】 | backend/app/graph/maintenance.py | 系统类型与孤儿清理 |
| 5 | 【修改】 | backend/app/graph/task_queue.py、worker.py | 写入哈希和审计 |
| 6 | 【修改】 | backend/app/graph/edit_service.py | 列表补齐系统类型 |
| 7 | 【运行验证】 | 未改内容、强制重抽和孤儿 | 任务状态与实体收敛 |

## 3. 按顺序修改文件与验证

### 步骤 1：【新增文件】backend/app/models/graph_extract_log.py

**编辑文件的完整地址：**

~~~text
./backend/app/models/graph_extract_log.py
~~~

**完整文件内容：**

~~~python
"""每个用户来源的最新一次抽取审计。"""
from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint, func

from app.models.base import Base


class GraphExtractLog(Base):
    __tablename__ = "graph_extract_logs"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "source_kind", "source_id",
            name="uq_graph_extract_user_source",
        ),
    )

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), index=True, nullable=False)
    source_kind = Column(String(10), nullable=False)
    source_id = Column(String(36), nullable=False)
    content_hash = Column(String(32), nullable=False)
    status = Column(String(20), default="pending", nullable=False)
    new_count = Column(Integer, default=0, nullable=False)
    update_count = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)
    finished_at = Column(DateTime(), nullable=True)
    updated_at = Column(
        DateTime(), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
~~~

**整体解释：** 这张表记录“同一个来源最近一次抽取结果”，不是每次执行的流水历史。唯一键避免并发任务写出两行；next 次抽取覆盖哈希、计数和错误。需要完整历史时再增加 append-only 执行表，本步先满足页面状态和幂等。

### 步骤 2：【修改】backend/app/models/graph_task.py

**编辑文件的完整地址：**

~~~text
./backend/app/models/graph_task.py
~~~

**修改定位与前后对照：** 增加标题、内容哈希、载荷和强制标记。

~~~diff
 from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint, func
+from sqlalchemy.dialects.mysql import LONGTEXT
@@
     source_id = Column(String(36), nullable=False)
+    title = Column(String(255), nullable=True)
+    content_hash = Column(String(32), nullable=False, default="")
+    payload = Column(Text().with_variant(LONGTEXT(), "mysql"), nullable=True)
+    force = Column(Integer, default=0, nullable=False)
     status = Column(String(20), default="pending", nullable=False)
~~~

**整体解释：** `payload` 让上传阶段已经切好的 Chunk、页码和图片路径随任务保存，Worker 不必再次猜测原始格式。`content_hash` 判断内容是否真的变化，`force` 区分用户主动重抽和普通保存；这里用 Integer 0/1，避免 SQLite 测试与 MySQL Boolean 的差异。

### 步骤 3：【修改】backend/app/db/db_config.py

**编辑文件的完整地址：**

~~~text
./backend/app/db/db_config.py
~~~

~~~diff
-from sqlalchemy import URL, text
+from sqlalchemy import URL, inspect, text
@@
+    from app.models.graph_extract_log import GraphExtractLog  # noqa: F401
@@
     async with async_engine.begin() as connection:
         await connection.run_sync(Base.metadata.create_all)
+        await _ensure_graph_task_columns(connection)
+
+
+async def _ensure_graph_task_columns(connection) -> None:
+    def column_names(sync_connection) -> set[str]:
+        inspector = inspect(sync_connection)
+        if not inspector.has_table("graph_tasks"):
+            return set()
+        return {
+            column["name"]
+            for column in inspector.get_columns("graph_tasks")
+        }
+
+    existing = await connection.run_sync(column_names)
+    changes = {
+        "title": "ADD COLUMN `title` VARCHAR(255) NULL",
+        "content_hash": (
+            "ADD COLUMN `content_hash` VARCHAR(32) NOT NULL DEFAULT ''"
+        ),
+        "payload": "ADD COLUMN `payload` LONGTEXT NULL",
+        "force": "ADD COLUMN `force` INT NOT NULL DEFAULT 0",
+    }
+    for name, operation in changes.items():
+        if name not in existing:
+            await connection.execute(text(
+                f"ALTER TABLE `graph_tasks` {operation}"
+            ))
~~~

**整体解释：** 新增模型必须注册到 `Base.metadata`，否则 `create_all` 不会建表。已有 `graph_tasks` 表不会因模型新增字段自动变更，因此建表后还要检查真实列集合，缺哪列就补哪列。迁移只执行固定的四条 DDL，不接收外部表名或 SQL，重复启动是幂等的。

### 步骤 4：【新增文件】backend/app/graph/maintenance.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/maintenance.py
~~~

**完整文件内容：**

~~~python
"""系统类型与孤儿实体维护。"""
from app.graph.neo4j_client import graph_driver

SYSTEM_TYPES = (
    ("concept", "概念", "#64748B"),
    ("person", "人物", "#2563EB"),
    ("organization", "组织", "#7C3AED"),
    ("technology", "技术", "#059669"),
)


async def ensure_system_types(user_id: str) -> None:
    for name, display, color in SYSTEM_TYPES:
        await graph_driver().execute_query(
            "MERGE (t:EntityType {user_id:$uid,name:$name}) "
            "ON CREATE SET t.id=randomUUID() "
            "SET t.display_name=$display,t.color=$color,t.is_system=true",
            uid=user_id, name=name, display=display, color=color,
        )


async def cleanup_orphan_entities(user_id: str, entity_ids: list[str]) -> int:
    if not entity_ids:
        return 0
    rows = (await graph_driver().execute_query(
        "MATCH (e:Entity {user_id:$uid}) WHERE e.id IN $ids "
        "AND NOT (e)<-[:MENTIONS]-(:Source {user_id:$uid}) "
        "AND NOT (e)<-[:MENTIONS]-(:Chunk {user_id:$uid}) "
        "DETACH DELETE e RETURN count(e) AS removed",
        uid=user_id, ids=entity_ids,
    )).records
    return int(rows[0]["removed"]) if rows else 0
~~~

**整体解释：** 系统类型按用户惰性种入，第一次打开类型列表或运行抽取时创建，不要求管理员预置全局节点。孤儿清理只在实体既没有 Source 提及、也没有 Chunk 提及时删除，手工实体仍可通过 `manual:true` 或没有候选来源保护，生产中应进一步显式排除手工实体。

### 步骤 5：【修改】backend/app/graph/task_queue.py 与 worker.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/task_queue.py
~~~

**修改定位与前后对照：** 入队时允许保存标题、哈希和 payload，重入队重置 force。

~~~diff
+import json
 from uuid import uuid4
@@
 async def enqueue_graph(
-    db: AsyncSession, user_id: str, source_kind: str, source_id: str
+    db: AsyncSession, user_id: str, source_kind: str, source_id: str,
+    *, title: str = "", content_hash: str = "", payload: dict | None = None,
+    force: bool = False,
 ) -> None:
@@
         db.add(GraphTask(
             id=str(uuid4()), user_id=user_id, source_kind=source_kind,
-            source_id=source_id, status="pending", attempts=0,
+            source_id=source_id, title=title, content_hash=content_hash,
+            payload=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
+            force=int(force), status="pending", attempts=0,
         ))
     else:
+        row.title = title
+        row.content_hash = content_hash
+        row.payload = json.dumps(payload, ensure_ascii=False) if payload is not None else None
+        row.force = int(force)
         row.status = "pending"
~~~

**编辑文件的完整地址：**

~~~text
./backend/app/graph/worker.py
~~~

~~~diff
+import hashlib
+from datetime import UTC, datetime
+from sqlalchemy import delete
+from app.graph.graph_store import delete_source, entity_id, replace_source
+from app.graph.maintenance import cleanup_orphan_entities
+from app.models.graph_extract_log import GraphExtractLog
@@
+def _now() -> datetime:
+    return datetime.now(UTC).replace(tzinfo=None)
+
+
+async def _save_audit(
+    *, user_id: str, kind: str, source_id: str, content_hash: str,
+    status: str, new_count: int = 0, update_count: int = 0,
+    error: str | None = None,
+) -> None:
+    async with AsyncSessionLocal() as db:
+        log = await db.scalar(select(GraphExtractLog).where(
+            GraphExtractLog.user_id == user_id,
+            GraphExtractLog.source_kind == kind,
+            GraphExtractLog.source_id == source_id,
+        ))
+        if log is None:
+            log = GraphExtractLog(
+                id=str(uuid4()), user_id=user_id,
+                source_kind=kind, source_id=source_id,
+                content_hash=content_hash, status=status,
+            )
+            db.add(log)
+        log.content_hash = content_hash
+        log.status = status
+        log.new_count = new_count
+        log.update_count = update_count
+        log.error_message = error
+        log.finished_at = _now() if status in {"success", "failed"} else None
+        await db.commit()
@@
         if source is None:
             await delete_source(user_id, kind, source_id)
             await delete_chunks(user_id, kind, source_id)
+            async with AsyncSessionLocal() as db:
+                await db.execute(delete(GraphExtractLog).where(
+                    GraphExtractLog.user_id == user_id,
+                    GraphExtractLog.source_kind == kind,
+                    GraphExtractLog.source_id == source_id,
+                ))
+                await db.commit()
         else:
+            body_hash = hashlib.md5(content.encode()).hexdigest()
+            async with AsyncSessionLocal() as db:
+                previous_log = await db.scalar(select(GraphExtractLog).where(
+                    GraphExtractLog.user_id == user_id,
+                    GraphExtractLog.source_kind == kind,
+                    GraphExtractLog.source_id == source_id,
+                    GraphExtractLog.status == "success",
+                    GraphExtractLog.content_hash == body_hash,
+                ))
+            if not force and previous_hash == body_hash and previous_log is not None:
+                async with AsyncSessionLocal() as db:
+                    current = await db.scalar(select(GraphTask).where(
+                        GraphTask.id == task_id,
+                    ).with_for_update())
+                    if current and current.run_token == token:
+                        current.status = "completed"
+                        current.run_token = None
+                        current.error_message = None
+                        await db.commit()
+                return True
+            await _save_audit(
+                user_id=user_id, kind=kind, source_id=source_id,
+                content_hash=body_hash, status="pending",
+            )
+            old_rows = (await graph_driver().execute_query(
+                "MATCH (:Source {user_id:$uid,kind:$kind,id:$sid})"
+                "-[:MENTIONS]->(e:Entity) RETURN collect(e.id) AS ids",
+                uid=user_id, kind=kind, sid=source_id,
+            )).records
+            old_ids = old_rows[0]["ids"] if old_rows else []
             result = await extract_entities(content)
             await replace_source(user_id, kind, source_id, title, result)
             await replace_chunks(user_id, kind, source_id, title, content)
+            new_ids = {entity_id(user_id, item.name) for item in result.entities}
+            await cleanup_orphan_entities(
+                user_id, [value for value in old_ids if value not in new_ids],
+            )
+            await _save_audit(
+                user_id=user_id, kind=kind, source_id=source_id,
+                content_hash=body_hash, status="success",
+                new_count=len(result.entities),
+                update_count=len(result.relations),
+            )
@@
     except Exception as exc:
         error = str(exc)[:500]
+        if body_hash:
+            try:
+                await _save_audit(
+                    user_id=user_id, kind=kind, source_id=source_id,
+                    content_hash=body_hash, status="failed", error=error,
+                )
+            except Exception:
+                pass
~~~

**整体解释：** 入队函数从“只传来源”升级为携带构建快照。Worker 先查最近一次成功日志；内容哈希相同且不是强制重抽时直接完成任务，不再调用模型。真正抽取前先把审计状态置为 pending，成功后记录实体/关系计数，异常时写 failed 和截断后的错误。孤儿清理只处理旧结果中本次消失的实体，并再次确认没有其他 Source/Chunk 提及。

### 步骤 6：【修改】backend/app/graph/edit_service.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/edit_service.py
~~~

~~~diff
 async def list_types(user_id: str) -> list[dict]:
+    from app.graph.maintenance import ensure_system_types
+    await ensure_system_types(user_id)
     rows = (await graph_driver().execute_query(
@@
-    return [{**row.data(), "is_system": False} for row in rows]
+    return [{**row.data(), "is_system": bool(row.data().get("is_system", False))} for row in rows]
~~~

**整体解释：** 打开类型列表时惰性补系统类型，不把系统类型写死在前端颜色表。用户在 GraphPage 初始加载 `types` 时就能看到默认分类，抽取也能按类型名映射到这些节点。

### 步骤 7：【运行验证】内容未变、强制重抽和孤儿

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv run python -m compileall -q app main.py
~~~

连续保存同一篇不变笔记，预期第二次任务根据哈希跳过模型调用或快速完成；手动点击重抽时 `force=1`，必须重新执行。把正文中的 `FastAPI` 删除后重抽，旧的 `FastAPI` 来源关系应被撤销；如果实体没有其他来源和 Chunk 提及，应被清理。请求类型列表时，四个系统类型必须存在且 `is_system=true`。

**本次实际验证：** 已对真实 MySQL 连续执行 `init_db()`，确认 `graph_tasks` 最终包含 `title/content_hash/payload/force`，并创建了 `graph_extract_logs`。临时插入任务和成功日志后调用抽取日志读取逻辑，返回哈希 `abc123`、状态 `success`、新增 4、更新 3，随后删除测试行。真实 Neo4j 中系统类型数量为 4；构造一个无来源实体和一个有 `Source` 提及的实体后运行清理，返回删除 1 个，预期保留的实体仍存在。验证使用独立临时 `user_id`，结束后已清理该测试子图。这里发现 Neo4j 5 不接受把 `ON CREATE SET` 写在普通 `SET` 之后；当前代码和测试均已修正。

