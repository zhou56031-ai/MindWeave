# 第 42 篇：MySQL 图谱任务、重试与独立 Worker

## 1. 本篇要接通的真实能力

MySQL 笔记提交与 Neo4j 图写入无法靠一次普通 commit 保证同时成功。本篇在 MySQL 中记录待构建任务，独立 Worker 从任务表认领、读取最新已提交正文、抽取并写图；失败保留状态供重试。HTTP 保存笔记不用等模型。这里采用最终一致：任务仍 pending 时图可能暂时旧；页面可看到状态后再提示刷新。队列技术比较见 [Q21](technology-routes/Q21-persistent-work-queues.md)。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 文件 | 用途 |
|---:|---|---|---|
| 1 | 【新增文件】 | backend/app/models/graph_task.py | 任务状态与唯一来源 |
| 2 | 【修改】 | backend/app/db/db_config.py | 注册 MySQL 表 |
| 3 | 【新增文件】 | backend/app/graph/task_queue.py | 同事务入队 |
| 4 | 【新增文件】 | backend/app/graph/worker.py | 认领、抽取、写图、重试 |
| 5 | 【修改】 | backend/app/services/note_service.py、knowledge_service.py | 内容变化时入队 |

Worker 是独立进程；本篇没有用 FastAPI BackgroundTasks 冒充持久队列。下列修改只针对复刻目录。

## 3. 按顺序修改文件与验证

### 步骤 1：【新增文件】backend/app/models/graph_task.py

**编辑文件的完整地址：**

~~~text
./backend/app/models/graph_task.py
~~~

**完整文件内容：**

~~~python
"""每个用户来源最多一条最新图构建任务。"""
from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint, func
from app.models.base import Base


class GraphTask(Base):
    __tablename__ = "graph_tasks"
    __table_args__ = (
        UniqueConstraint("user_id", "source_kind", "source_id", name="uq_graph_task_source"),
    )

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), nullable=False, index=True)
    source_kind = Column(String(10), nullable=False)
    source_id = Column(String(36), nullable=False)
    status = Column(String(20), default="pending", nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    run_token = Column(String(36), nullable=True)
    error_message = Column(Text, nullable=True)
    updated_at = Column(DateTime(), server_default=func.now(), onupdate=func.now(), nullable=False)
~~~

**整体解释：** 一条任务是某份资料的“待处理工单”，不是正文副本。唯一键让同一用户的一篇笔记反复编辑仍只有一张最新工单；Worker 真正执行时再读最新已提交内容，避免处理旧载荷。attempts 与 error_message 让故障可观察；run_token 识别过期执行者。

### 步骤 2：【修改】backend/app/db/db_config.py

**编辑文件的完整地址：**

~~~text
./backend/app/db/db_config.py
~~~

**修改定位与前后对照：** init_db 的模型导入清单。

~~~diff
     from app.models.chat_history import ChatSession, ChatMessage  # noqa: F401
+    from app.models.graph_task import GraphTask  # noqa: F401
~~~

**整体解释：** 表类只有被导入才会登记进 Base.metadata；应用启动执行 create_all 时才会建缺失表。未来改字段要用迁移，不能指望 create_all 自动修改旧表。

### 步骤 3：【新增文件】backend/app/graph/task_queue.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/task_queue.py
~~~

**完整文件内容：**

~~~python
"""与原业务写入共用 MySQL 事务的任务登记。"""
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.graph_task import GraphTask


async def enqueue_graph(
    db: AsyncSession, user_id: str, source_kind: str, source_id: str
) -> None:
    if source_kind not in {"note", "doc"}:
        raise ValueError("来源类型不支持")
    row = await db.scalar(
        select(GraphTask).where(
            GraphTask.user_id == user_id,
            GraphTask.source_kind == source_kind,
            GraphTask.source_id == source_id,
        ).with_for_update()
    )
    if row is None:
        db.add(GraphTask(
            id=str(uuid4()), user_id=user_id, source_kind=source_kind,
            source_id=source_id, status="pending", attempts=0,
        ))
    else:
        row.status = "pending"
        row.attempts = 0
        row.run_token = None
        row.error_message = None
    # 调用方与原业务行一起 commit；这里绝不提前提交。
~~~

**整体解释：** 这张工单要和笔记或文档的变化放进同一 MySQL 事务：原内容保存失败，工单也不能出现；工单插入失败，原保存也回滚。若同时首次修改同一来源，唯一键是最后保险，服务应把冲突作为可重试错误处理。图更新仍在稍后发生，因此前端不能把“工单已入队”说成“图已经构建”。

### 步骤 4：【新增文件】backend/app/graph/worker.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/worker.py
~~~

**完整文件内容：**

~~~python
"""独立进程消费图构建任务：python -m app.graph.worker。"""
import asyncio
from uuid import uuid4

from sqlalchemy import select

from app.db.db_config import AsyncSessionLocal, async_engine, init_db
from app.graph.extractor import extract_entities
from app.graph.graph_store import delete_source, replace_source
from app.graph.neo4j_client import close_graph_driver, ensure_graph_schema
from app.models.graph_task import GraphTask
from app.models.knowledge_document import KnowledgeDocument
from app.models.note import Note


async def process_one() -> bool:
    async with AsyncSessionLocal() as db:
        task = await db.scalar(
            select(GraphTask).where(GraphTask.status == "pending")
            .order_by(GraphTask.updated_at, GraphTask.id)
            .limit(1).with_for_update(skip_locked=True)
        )
        if task is None:
            return False
        task_id = task.id
        token = str(uuid4())
        task.status = "running"
        task.run_token = token
        task.attempts += 1
        user_id, kind, source_id = task.user_id, task.source_kind, task.source_id
        await db.commit()

    try:
        async with AsyncSessionLocal() as db:
            if kind == "note":
                source = await db.scalar(select(Note).where(
                    Note.id == source_id, Note.user_id == user_id))
                title = source.title if source else ""
                content = source.content if source else ""
            else:
                source = await db.scalar(select(KnowledgeDocument).where(
                    KnowledgeDocument.id == source_id,
                    KnowledgeDocument.user_id == user_id))
                title = source.filename if source else ""
                content = source.content if source else ""
        if source is None:
            await delete_source(user_id, kind, source_id)
        else:
            result = await extract_entities(content)
            async with AsyncSessionLocal() as db:
                current = await db.scalar(select(GraphTask).where(GraphTask.id == task_id))
                if current is None or current.run_token != token:
                    return True
            await replace_source(user_id, kind, source_id, title, result)
        error = None
    except Exception as exc:
        error = str(exc)[:500]

    async with AsyncSessionLocal() as db:
        current = await db.scalar(select(GraphTask).where(GraphTask.id == task_id).with_for_update())
        if current is None or current.run_token != token:
            return True
        current.status = ("pending" if current.attempts < 3 else "failed") if error else "completed"
        current.error_message = error
        current.run_token = None
        await db.commit()
    return True


async def main() -> None:
    await init_db()
    await ensure_graph_schema()
    try:
        while True:
            if not await process_one():
                await asyncio.sleep(2)
    finally:
        await close_graph_driver()
        await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
~~~

**整体解释：** Worker 先短暂锁住 pending 工单并发给自己一个令牌，提交后才去做慢模型调用，避免长时间占住 MySQL 行锁。写图前重新核对令牌，编辑导致重新入队时旧 Worker 不应宣称完成。若重入队恰好发生在核对后、写图期间，图可能短暂显示旧内容；新 pending 任务随后会重建，这就是最终一致。进程在 running 时崩溃会留下悬空任务；正式运行前要把超时 running 重置为 pending，或给任务加租约字段，此版本尚未自动恢复。

### 步骤 5：【修改】backend/app/services/note_service.py

**编辑文件的完整地址：**

~~~text
./backend/app/services/note_service.py
~~~

**修改定位与前后对照：** create_note、update_note、delete_note 的现有 commit 之前入队；批量删除同样逐条入队。

~~~diff
+from app.graph.task_queue import enqueue_graph
@@ async def create_note(
-        await db.commit()
+        await enqueue_graph(db, user_id, "note", note.id)
+        await db.commit()
@@ async def update_note(
         for name, value in changes.items():
             setattr(note, name, value)
+        await enqueue_graph(db, user_id, "note", note.id)
         await db.commit()
@@ async def delete_note(
         await db.delete(note)
+        await enqueue_graph(db, user_id, "note", note_id)
         await db.commit()
@@ async def batch_delete_notes(
         for note in notes:
             await db.delete(note)
+            await enqueue_graph(db, user_id, "note", note.id)
         await db.commit()
@@ async def delete_category(
         for note in notes:
             await db.delete(note)
+            await enqueue_graph(db, user_id, "note", note.id)
         await db.commit()
~~~

**整体解释：** 笔记保存的那次 MySQL 事务把“内容变化”和“待重建工单”一起装订；Worker 之后读到的是已提交最终版本。删除也入队，Worker 读不到来源时会清图。按分类批量删除同样生成撤图任务。这里不为置顶和分类调整重抽实体，因为正文没有变；若图展示依赖标题，更新标题已经包含在 update_note 的入队中。

### 步骤 6：【修改】backend/app/services/knowledge_service.py

**编辑文件的完整地址：**

~~~text
./backend/app/services/knowledge_service.py
~~~

**修改定位与前后对照：** add_document 和 delete_document 的 commit 前入队，clean_all 则对每个文档入队。

~~~diff
+from app.graph.task_queue import enqueue_graph
@@ async def add_document(
             db.add_all([
@@
             ])
+            await enqueue_graph(db, user_id, "doc", document.id)
             await db.commit()
@@ async def delete_document(
         await db.delete(document)
+        await enqueue_graph(db, user_id, "doc", document.id)
         await db.commit()
@@ async def clean_all(
-        result = await db.execute(select(KnowledgeDocument.id).where(
+        result = await db.execute(select(KnowledgeDocument.id).where(
@@
         ids = list(result.scalars().all())
@@
+        for document_id in ids:
+            await enqueue_graph(db, user_id, "doc", document_id)
         await db.commit()
~~~

**整体解释：** 文档导入成功时只承诺 MySQL 文本可读和工单存在，不承诺图马上完成。删除和批量清理都留下撤图工单；如果漏掉这个动作，图会继续展示已经删掉的来源。与笔记相同，任务和文档变化共用当前数据库事务。

### 步骤 7：【运行验证】启动 Worker 与错误恢复

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv run python -m compileall -q app main.py
uv run python -m app.graph.worker
~~~

第二条命令需单独终端保持运行。用自己的临时笔记创建、修改、删除，核对 graph_tasks 依次 pending/running/completed，图来源随之变化。用无效图密码验证 failed 或 pending 和错误记录，不应该让笔记事务在 Worker 阶段回滚。本篇 running 崩溃恢复仍是明确待补可靠性项，下一篇会先让状态可见。
