# 第 59 篇：MySQL Checkpoint、审批快照与跨请求状态

## 1. 本篇要接通的真实能力

当前 AgentRun 只保存写入提案和最终结果，无法查看 Agent 已执行过哪些工具，也没有参考项目 `/chat/session/{id}/approval` 快照接口。本篇增加 LangGraph 的 MySQL checkpoint 两表、独立 saver 和审批快照。AgentRun 仍是业务执行权威，checkpoint 负责保存模型图状态；两种记录不要混成一张表。技术路线见 [Q26](technology-routes/Q26-langgraph-and-durable-state.md)。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 文件 | 职责 |
|---:|---|---|---|
| 1 | 【新增文件】 | backend/app/models/agent_checkpoint.py | checkpoint 两表 |
| 2 | 【修改】 | backend/app/db/db_config.py | 注册 checkpoint 表 |
| 3 | 【新增文件】 | backend/app/agent/checkpoint/mysql_saver.py | BaseCheckpointSaver 实现 |
| 4 | 【新增文件】 | backend/app/agent/checkpoint/factory.py | 单例与线程 ID |
| 5 | 【修改】 | backend/app/agent/workflow.py | 编译图时注入 checkpointer |
| 6 | 【修改】 | backend/app/services/chat_stream_service.py | 为每次会话指定 thread |
| 7 | 【修改】 | backend/app/agent/run_store.py、chat_router.py | 审批快照接口 |
| 8 | 【运行验证】 | 中断、重启与快照 | 状态可读且不可重复执行 |

## 3. 按顺序修改文件与验证

### 步骤 1：【新增文件】backend/app/models/agent_checkpoint.py

**编辑文件的完整地址：**

~~~text
./backend/app/models/agent_checkpoint.py
~~~

**完整文件内容：**

~~~python
"""LangGraph 状态快照与中间写入。"""
from sqlalchemy import Column, Integer, LargeBinary, String
from sqlalchemy.dialects.mysql import LONGBLOB

from app.models.base import Base


class AgentCheckpoint(Base):
    __tablename__ = "agent_checkpoints"

    thread_id = Column(String(255), primary_key=True, index=True)
    checkpoint_ns = Column(String(255), primary_key=True, default="")
    checkpoint_id = Column(String(64), primary_key=True)
    parent_checkpoint_id = Column(String(64), nullable=True)
    type = Column(String(64), nullable=True)
    checkpoint = Column(LargeBinary().with_variant(LONGBLOB(), "mysql"))
    metadata_ = Column(
        LargeBinary().with_variant(LONGBLOB(), "mysql"), name="metadata",
    )


class AgentCheckpointWrite(Base):
    __tablename__ = "agent_checkpoint_writes"

    thread_id = Column(String(255), primary_key=True)
    checkpoint_ns = Column(String(255), primary_key=True, default="")
    checkpoint_id = Column(String(64), primary_key=True)
    task_id = Column(String(64), primary_key=True)
    idx = Column(Integer, primary_key=True)
    channel = Column(String(255), nullable=False)
    type = Column(String(64), nullable=True)
    value = Column(LargeBinary().with_variant(LONGBLOB(), "mysql"))


~~~

**整体解释：** 两张表保存“每个 superstep 的快照”和“尚未合并的中间写入”，与当前 LangGraph saver 版本一致。它们保存序列化后的 LangGraph 状态，不是可读业务字段；审批页仍应通过 AgentRun 展示工具名和参数，不能把二进制 checkpoint 直接返回浏览器。

### 步骤 2：【修改】backend/app/db/db_config.py

**编辑文件的完整地址：**

~~~text
./backend/app/db/db_config.py
~~~

**修改定位与前后对照：** 在 `init_db()` 的模型导入清单注册 checkpoint。

~~~diff
     from app.models.agent_run import AgentRun  # noqa: F401
+    from app.models.agent_checkpoint import (  # noqa: F401
+        AgentCheckpoint, AgentCheckpointWrite,
+    )
     from app.models.graph_task import GraphTask  # noqa: F401
~~~

**整体解释：** SQLAlchemy 只会为已经导入的模型建表。注册后，应用启动的 `create_all` 会新增三张缺失表；已有表结构不会自动迁移，生产环境仍要用迁移脚本管理版本。

### 步骤 3：【新增文件】backend/app/agent/checkpoint/mysql_saver.py

**执行目录的完整地址：**

~~~text
.
~~~

参考项目已经提供经过大量测试的 MySQL saver。直接复制完整实现，避免在教程中重抄数百行序列化代码：

~~~bash
mkdir -p "./backend/app/agent/checkpoint"
cp "./backend/app/agent/checkpoint/mysql_saver.py" \
   "./backend/app/agent/checkpoint/mysql_saver.py"
~~~

再新增包初始化文件：

**编辑文件的完整地址：**

~~~text
./backend/app/agent/checkpoint/__init__.py
~~~

~~~python
"""LangGraph MySQL checkpoint。"""
~~~

**整体解释：** 这个 saver 使用 `JsonPlusSerializer` 处理 BaseMessage，并根据 MySQL 方言使用 `ON DUPLICATE KEY UPDATE`。复制现成实现比在教程里手写二进制协议更可靠；复制后要确认文件仍是 MIT 许可项目的一部分，并保留来源说明。

### 步骤 4：【新增文件】backend/app/agent/checkpoint/factory.py

**编辑文件的完整地址：**

~~~text
./backend/app/agent/checkpoint/factory.py
~~~

**完整文件内容：**

~~~python
"""按进程复用 MySQL checkpointer。"""
from app.agent.checkpoint.mysql_saver import MySQLCheckpointSaver
from app.db.db_config import AsyncSessionLocal

_saver: MySQLCheckpointSaver | None = None


def get_checkpointer() -> MySQLCheckpointSaver:
    global _saver
    if _saver is None:
        _saver = MySQLCheckpointSaver(session_factory=AsyncSessionLocal)
    return _saver


def checkpoint_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}
~~~

**整体解释：** saver 是无业务状态的连接包装器，可以按进程复用；`thread_id` 才区分不同会话或运行。把配置生成集中到一处，防止一个调用方用 session_id、另一个用 run_id，导致快照看起来存在但无法恢复。

### 步骤 5：【修改】backend/app/agent/workflow.py

**编辑文件的完整地址：**

~~~text
./backend/app/agent/workflow.py
~~~

**修改定位与前后对照：** 编译图时注入 checkpointer。

~~~diff
+from app.agent.checkpoint.factory import get_checkpointer
@@
-agent_workflow = builder.compile()
+agent_workflow = builder.compile(checkpointer=get_checkpointer())
~~~

**整体解释：** 编译后的图会在每个 superstep 写 checkpoint。没有 `thread_id` 的调用会失败，这是防止不同请求状态混在一起的硬约束。图节点本身仍只处理当前请求。

### 步骤 6：【修改】backend/app/services/chat_stream_service.py

**编辑文件的完整地址：**

~~~text
./backend/app/services/chat_stream_service.py
~~~

**修改定位与前后对照：** 调用图时提供 `thread_id=session_id`。

~~~diff
+from app.agent.checkpoint.factory import checkpoint_config
@@
-        decision = await agent_workflow.ainvoke({
-            "user_id": user_id, "query": query,
-        })
+        decision = await agent_workflow.ainvoke(
+            {"user_id": user_id, "query": query},
+            checkpoint_config(session_id),
+        )
~~~

**整体解释：** 同一聊天会话复用同一个 thread，刷新页面后还能看到上一轮工具状态；新会话使用新 UUID，不需要清理旧数据才能开始。会话删除时应同时删除对应 checkpoint thread，这一点在下面验证并补清理。

### 步骤 7：【修改】backend/app/agent/run_store.py 与 chat_router.py

**编辑文件的完整地址：**

~~~text
./backend/app/agent/run_store.py
~~~

**修改定位与前后对照：** 增加审批快照读取，已处理运行也能看到结果。

~~~diff
 async def pending(user_id: str, session_id: str) -> dict | None:
@@
         return {
             "run_id": run.id,
             "query": run.query,
             "payload": approval_payload(run.proposal),
         }
+
+
+async def approval_snapshot(user_id: str, session_id: str) -> dict | None:
+    async with AsyncSessionLocal() as db:
+        session = await chat_session_service.owned(db, user_id, session_id)
+        run = await db.scalar(select(AgentRun).where(
+            AgentRun.session_id == session.id,
+            AgentRun.user_id == user_id,
+        ).order_by(AgentRun.updated_at.desc()).limit(1))
+        if run is None:
+            return None
+        return {
+            "run_id": run.id,
+            "query": run.query,
+            "status": run.status,
+            "active": run.id == session.pending_run_id and run.status == "pending",
+            "payload": approval_payload(run.proposal),
+            "result": run.result,
+        }
~~~

**编辑文件的完整地址：**

~~~text
./backend/app/router/chat_router.py
~~~

~~~diff
-from app.agent.run_store import pending
+from app.agent.run_store import approval_snapshot, pending
@@
 @chat_router.get("/session/{session_id}/pending")
@@
     return success_response(data=await pending(user_id, session_id))
+
+
+@chat_router.get("/session/{session_id}/approval")
+async def get_approval(
+    session_id: str,
+    user_id: str = Depends(get_current_user_id),
+) -> JSONResponse:
+    return success_response(data=await approval_snapshot(user_id, session_id))
~~~

**整体解释：** `pending` 只服务“现在还能不能审批”，`approval_snapshot` 服务“上次审批最后怎样了”。后者可以返回 completed/rejected，但仍先通过会话归属验证；别人的 session_id 统一 404，不泄漏提案标题和工具参数。

### 步骤 8：【运行验证】中断、重启与快照

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv run python -m compileall -q app main.py
~~~

创建一篇待审批笔记，确认 `agent_checkpoints` 中出现当前 session thread；重启后端后请求 `/chat/session/{id}/pending`，审批卡仍能恢复。拒绝后请求 `/approval`，状态应为 rejected 且 `active=false`。同一会话再次发起新提案，thread 不应混用旧 pending。删除会话时记得调用 `get_checkpointer().adelete_thread(session_id)`，避免孤儿 checkpoint。

