# 第 50 篇：人工审批、断线恢复与写操作防重

## 1. 本篇要接通的真实能力

前端 AIChat 收到 type=interrupt、run_id、payload 后会显示审批卡；刷新页面会请求 /chat/session/{id}/pending；点击同意或拒绝会 POST /chat/agent/resume，正文是 session_id 与 decisions 数组。本篇让这些现有前端代码真正工作。审批与业务写入之间是信任边界：必须重新检查会话归属、运行状态和已保存提案，不能相信浏览器重新提交的工具参数。设计取舍见 [Q27](technology-routes/Q27-human-approval-and-idempotency.md)。

同一运行只允许一次从 pending 进入 executing。批准之后，先执行写入并记录 completed，再生成回答；即使 SSE 断线，刷新后也不会重复执行。若进程恰好在业务写入提交后、completed 落库前崩溃，状态会留在 executing，系统停止自动重试并要求人工核对，避免再次创建笔记。这个不确定窗口要在验收中明确观察。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 文件 | 职责 |
|---:|---|---|---|
| 1 | 【新增文件】 | backend/app/agent/run_store.py | 保存、认领、完成审批 |
| 2 | 【新增文件】 | backend/app/agent/approval_stream.py | 同意/拒绝后的 SSE |
| 3 | 【修改】 | backend/app/services/chat_stream_service.py | 初次请求生成 interrupt |
| 4 | 【修改】 | backend/app/router/chat_router.py | 待办查询与恢复路由 |
| 5 | 【运行验证】 | 浏览器与双账号 | 刷新、同意、拒绝、重复提交 |

第 49 篇只是搭好决策流；本篇才连接 HTTP。前端代码已经在复刻目录，无须重新编写。

## 3. 按顺序修改文件与验证

### 步骤 1：【新增文件】backend/app/agent/run_store.py

**编辑文件的完整地址：**

~~~text
./backend/app/agent/run_store.py
~~~

**完整文件内容：**

~~~python
"""MySQL 中的待审批运行：只按 JWT 用户身份访问。"""
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from app.db.db_config import AsyncSessionLocal
from app.models.agent_run import AgentRun
from app.models.chat_history import ChatSession
from app.services.chat_session_service import chat_session_service


def approval_payload(proposal: dict) -> dict:
    return {
        "action_requests": [{
            "name": proposal["tool"],
            "args": proposal["arguments"],
            "description": proposal["description"],
        }],
        "review_configs": [{
            "action_name": proposal["tool"],
            "allowed_decisions": ["approve", "reject"],
        }],
    }


async def save_pending(
    user_id: str, session_id: str, existing_id: str | None,
    query: str, proposal: dict,
) -> AgentRun:
    async with AsyncSessionLocal() as db:
        session = await chat_session_service.ensure(
            db, user_id, existing_id, query[:60], new_id=session_id,
        )
        session = await db.scalar(select(ChatSession).where(
            ChatSession.id == session.id,
            ChatSession.user_id == user_id,
        ).with_for_update())
        if session.pending_run_id:
            raise HTTPException(status_code=409, detail="此会话已有待审批操作")
        run = AgentRun(
            id=str(uuid4()), session_id=session.id, user_id=user_id,
            status="pending", query=query, proposal=proposal,
        )
        db.add(run)
        session.pending_run_id = run.id
        await db.commit()
        return run


async def pending(user_id: str, session_id: str) -> dict | None:
    async with AsyncSessionLocal() as db:
        session = await chat_session_service.owned(db, user_id, session_id)
        if not session.pending_run_id:
            return None
        run = await db.scalar(select(AgentRun).where(
            AgentRun.id == session.pending_run_id,
            AgentRun.user_id == user_id,
            AgentRun.session_id == session_id,
            AgentRun.status == "pending",
        ))
        if run is None:
            return None
        return {
            "run_id": run.id, "query": run.query,
            "payload": approval_payload(run.proposal),
        }


async def claim(user_id: str, session_id: str) -> tuple[str, dict, str, str]:
    async with AsyncSessionLocal() as db:
        session = await db.scalar(
            select(ChatSession).where(
                ChatSession.id == session_id, ChatSession.user_id == user_id,
            ).with_for_update()
        )
        if session is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        if not session.pending_run_id:
            raise HTTPException(status_code=409, detail="没有可恢复的审批")
        run = await db.scalar(select(AgentRun).where(
            AgentRun.id == session.pending_run_id,
            AgentRun.user_id == user_id,
            AgentRun.session_id == session_id,
        ).with_for_update())
        if run is None or run.status != "pending":
            raise HTTPException(status_code=409, detail="审批已处理或正在处理")
        run.status = "executing"
        await db.commit()
        return run.id, run.proposal, run.query, session_id


async def finish(
    user_id: str, session_id: str, run_id: str,
    status: str, result: str,
) -> None:
    async with AsyncSessionLocal() as db:
        session = await db.scalar(
            select(ChatSession).where(
                ChatSession.id == session_id, ChatSession.user_id == user_id,
            ).with_for_update()
        )
        run = await db.scalar(select(AgentRun).where(
            AgentRun.id == run_id, AgentRun.user_id == user_id,
            AgentRun.session_id == session_id,
        ).with_for_update())
        if session is None or run is None or run.status != "executing":
            raise HTTPException(status_code=409, detail="运行状态冲突")
        run.status = status
        run.result = result
        session.pending_run_id = None
        await db.commit()
~~~

**整体解释：** save_pending 先保证会话存在，才把服务端校验过的 proposal 放入 AgentRun，并把 run.id 挂到 ChatSession.pending_run_id。pending 只返回当前用户、当前会话、仍处于 pending 的提案。claim 在数据库行锁内把 pending 改成 executing：两个同时到达的“同意”请求，只有一个能拿到执行权。finish 清除待办，刷新页面就不会再弹旧卡。会话与运行状态不能分两次随意更新，否则刷新时可能看见一半旧、一半新。

### 步骤 2：【新增文件】backend/app/agent/approval_stream.py

**编辑文件的完整地址：**

~~~text
./backend/app/agent/approval_stream.py
~~~

**完整文件内容：**

~~~python
"""审批恢复后的 SSE：写操作先落地，再解释结果。"""
from collections.abc import AsyncIterator
from fastapi import HTTPException

from app.agent.run_store import claim, finish
from app.agent.tools import execute_approved_write
from app.db.db_config import AsyncSessionLocal
from app.services.chat_session_service import chat_session_service
from app.services.chat_stream_service import frame
from app.services.deepseek_client import deepseek_client


async def resume_events(
    user_id: str, session_id: str, decision: str,
) -> AsyncIterator[str]:
    try:
        run_id, proposal, query, _ = await claim(user_id, session_id)
    except HTTPException as exc:
        yield frame({"type": "error", "content": str(exc.detail)})
        yield frame({"type": "done", "session_id": session_id})
        return
    if decision == "reject":
        answer = "已取消这项操作，没有写入数据。"
        await finish(user_id, session_id, run_id, "rejected", answer)
        async with AsyncSessionLocal() as db:
            session = await chat_session_service.owned(db, user_id, session_id)
            await chat_session_service.append_turn(db, session, query, answer)
        yield frame({"type": "response", "content": answer, "session_id": session_id})
        yield frame({"type": "done", "session_id": session_id})
        return

    yield frame({
        "type": "thinking", "stage": "tool_execution",
        "content": "已获得同意，正在执行受控操作",
    })
    try:
        async with AsyncSessionLocal() as db:
            result = await execute_approved_write(db, user_id, proposal)
        # 业务写入服务已提交；立即记录完成，断线后绝不重做。
        await finish(user_id, session_id, run_id, "completed", result)
    except Exception:
        # 如果业务提交与 finish 之间失败，保留 executing 待人工核对。
        yield frame({"type": "error", "content": "操作状态需要核对，请勿重复点击"})
        yield frame({"type": "done", "session_id": session_id})
        return

    parts: list[str] = []
    try:
        async for part in deepseek_client.stream_chat([
            {"role": "system", "content": "只根据工具执行结果解释，不声称执行了其他操作。"},
            {"role": "user", "content": f"用户请求：{query}\n工具结果：{result}"},
        ], max_tokens=300):
            parts.append(part)
            yield frame({"type": "response", "content": part, "session_id": session_id})
        answer = "".join(parts).strip() or result
        async with AsyncSessionLocal() as db:
            session = await chat_session_service.owned(db, user_id, session_id)
            await chat_session_service.append_turn(db, session, query, answer)
    except Exception:
        # 此时工具可能已经成功，不把“回答失败”描述成“写入失败”。
        yield frame({"type": "error", "content": "操作已完成，但回答未保存；请刷新目标页面核对"})
    yield frame({"type": "done", "session_id": session_id})
~~~

**整体解释：** 审批是先锁定运行、再执行工具。被拒绝时完全跳过工具，只存一条取消说明。被同意时先让业务服务提交，再立刻把运行标为 completed，最后才让模型把结果说成人话。模型解释失败不能抹掉已经发生的数据库写入。唯一无法自动判定的窗口是业务已提交但 finish 尚未提交：此时保留 executing，禁止重试，人工按 run_id 和业务表核对。

### 步骤 3：【修改】backend/app/services/chat_stream_service.py

**编辑文件的完整地址：**

~~~text
./backend/app/services/chat_stream_service.py
~~~

**修改定位与前后对照：** 在 chat_events 的第一条 thinking 事件之前调用图；写入提案产生 interrupt 后结束流，只读结果继续作为模型背景资料。

~~~diff
 from app.db.db_config import AsyncSessionLocal
+from app.agent.workflow import agent_workflow
+from app.agent.run_store import approval_payload, save_pending
@@
 async def chat_events(
     user_id: str, query: str, session_id: str, existing_id: str | None
 ) -> AsyncIterator[str]:
+    try:
+        decision = await agent_workflow.ainvoke({
+            "user_id": user_id, "query": query,
+        })
+        proposal = decision.get("proposal")
+        if proposal:
+            run = await save_pending(
+                user_id, session_id, existing_id, query, proposal,
+            )
+            yield frame({
+                "type": "interrupt", "session_id": session_id,
+                "run_id": run.id, "payload": approval_payload(proposal),
+            })
+            yield frame({"type": "done", "session_id": session_id})
+            return
+        tool_result = decision.get("tool_result")
+    except Exception:
+        yield frame({"type": "error", "content": "工具决策失败，本次未执行操作"})
+        yield frame({"type": "done", "session_id": session_id})
+        return
     yield frame({"type": "thinking", "stage": "agentic_plan",
@@
-            {"role": "user", "content": f"背景资料：\n{context or '没有检索到本地资料'}\n\n问题：{query}"},
+            {"role": "user", "content": (
+                f"工具读取结果：{tool_result or '无'}\n"
+                f"背景资料：\n{context or '没有检索到本地资料'}\n\n问题：{query}"
+            )},
~~~

**整体解释：** 普通问题可以先让工具读统计或回顾，再继续第 47 篇的检索和生成；写入问题必须停在 interrupt，让用户看到准确工具名与参数。初次提案阶段没有执行 execute_approved_write。这里故意不把图决策失败默默变成“已执行”，错误事件会让用户知道本次没有发生写入。若本地模型未配置，普通聊天也会被此处挡住；测试非 AI 功能时不调用该流即可。

### 步骤 4：【修改】backend/app/router/chat_router.py

**编辑文件的完整地址：**

~~~text
./backend/app/router/chat_router.py
~~~

**修改定位与前后对照：** 在现有 query_stream 之后加入两个接口；resume 的决策值只允许 approve/reject，不接受浏览器给出的工具参数。先在返回 StreamingResponse 前验证会话归属。

~~~diff
 from uuid import uuid4
+from typing import Literal
+from pydantic import BaseModel, Field
+from app.agent.approval_stream import resume_events
+from app.agent.run_store import pending
@@
 chat_router = APIRouter(prefix="/chat", tags=["chat"])
+
+
+class ApprovalDecision(BaseModel):
+    type: Literal["approve", "reject"]
+    message: str | None = Field(default=None, max_length=500)
+
+
+class ResumeRequest(BaseModel):
+    session_id: str
+    decisions: list[ApprovalDecision] = Field(min_length=1, max_length=1)
@@
 @chat_router.post("/agent/query/stream")
@@
     )
+
+
+@chat_router.get("/session/{session_id}/pending")
+async def get_pending(
+    session_id: str,
+    user_id: str = Depends(get_current_user_id),
+) -> JSONResponse:
+    return success_response(data=await pending(user_id, session_id))
+
+
+@chat_router.post("/agent/resume")
+async def resume(
+    payload: ResumeRequest,
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> StreamingResponse:
+    await chat_session_service.owned(db, user_id, payload.session_id)
+    await db.rollback()
+    return StreamingResponse(
+        resume_events(user_id, payload.session_id, payload.decisions[0].type),
+        media_type="text/event-stream",
+        headers={"Cache-Control": "no-cache"},
+    )
~~~

**整体解释：** 路由只做身份入口与数据形状检查；run_store 重新验证数据库里的用户与会话。前端虽然保存 run_id 用于显示，但 resume 只传 session_id，所以服务端必须从该会话的 pending_run_id 找运行，不能按任意客户端 run_id 执行。GET pending 返回 null 表示无待办；别人会话返回 404，不泄漏提案内容。

### 步骤 5：【运行验证】审批状态与断线

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv run python -m compileall -q app main.py
~~~

以测试账号在 AIChat 明确要求“创建标题为审批练习的笔记”。收到 interrupt 后刷新页面，待办卡应从 GET pending 恢复；此时 notes 表不能增加行。先用“拒绝”验证无写入，再发起新请求并“同意”，应只增加一条笔记。对同一 session_id 同时提交两次 approve，只有一次能认领 pending；第二次应收到 SSE 错误事件，不得创建第二条。换另一账号请求该会话，应得到 404。审批后断开 SSE，再刷新笔记列表，已完成写入仍在；执行中状态若异常停留，应按 run_id 人工核对，不要直接重置为 pending。
