# 第 34 篇：会话列表、历史读取与删除的用户边界

> 前置：第 33 篇完成后的复刻后端。本文是待操作教程，写作时对照了正式复刻目录和参考项目；文中的预期结果不是正式工程已实测的结果。
> 成果：前端 Sessions 与 AIChat 使用的 GET /chat/sessions/{user_id}、GET/DELETE /chat/session/{id} 有真实 MySQL 数据。
> 范围：只指导后端；前端继续直接使用已经复制的源码。新增文件给完整代码，修改文件只给本次 diff，不重复整份最终源码。

## 1. 本篇要接通的真实能力

第 33 篇有了表，但前端会话列表仍请求不到数据。这个阶段先把“已有会话的读取与删除”接通；会话创建由第 36 篇第一次聊天时触发。参考前端的列表 URL 含 user_id，但 URL 是客户端可改的，不能把它当权限证明。服务层每个查询都要以 JWT 确认的用户 ID 限制会话范围；历史消息只在确认会话归属后读取。

本篇从复刻项目现有代码继续，路径和导入均从下面这个固定目录算起。不要在参考仓库执行修改；那份源码用于比较接口与数据流。代码注释中【新增】标出本步新行为，diff 的正负号只用于定位，不要粘进 Python 文件。涉及账号或模型密钥时只用本机 `.env`，不把真实值写进教程或 Git。

**复刻根目录：**

```text
.
```

**本篇接口或产物契约：**

- `GET /chat/sessions/{user_id}` 与 `GET /chat/sessions` 返回 data.sessions；路径 user_id 必须与 JWT 用户一致。
- `GET /chat/session/{id}` 返回 session_id、按 id 排序的 history 数组与 pending_run_id。
- `DELETE /chat/session/{id}` 只删本人会话和其消息；他人或不存在的会话统一 404。
- 本篇不生成模型回答；没有会话时列表为空，不插入占位数据。

**本篇与参考实现的差异：** 参考项目有更完整的 Agent 待审批快照；本阶段 pending_run_id 为模型字段，详情可返回其值，但不宣称已经具备审批恢复。

**技术路线阅读：** 异步 ORM 与请求会话的取舍继续看 [Q06](technology-routes/Q06-sqlalchemy-async-orm.md)。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 路径 | 本步职责 |
|---:|---|---|---|
| 1 | 【新增文件】 | `backend/app/services/chat_session_service.py` | 把会话创建、列表、详情、历史和删除集中到服务层 |
| 2 | 【新增文件】 | `backend/app/router/chat_router.py` | 提供前端现有会话 URL |
| 3 | 【修改】 | `backend/main.py` | 注册聊天路由组 |

先看清楚上表：新文件的父目录若已存在就复用；步骤之间的 import 按顺序出现。每做完一个文件就做该步的小检查，不要把所有代码贴完才第一次启动。修改已有文件时请按 diff 的上下文搜索函数名或配置项，行号只供参考，因为上一章或你自己的改动可能改变行号。

## 3. 按顺序修改文件与验证

### 步骤 1：【新增文件】 `backend/app/services/chat_session_service.py`

**文件职责：** 把会话创建、列表、详情、历史和删除集中到服务层

**编辑文件的完整地址：**

```text
./backend/app/services/chat_session_service.py
```

**完整文件内容：**

```python
"""聊天会话的用户范围查询与持久化。"""
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.chat_history import ChatMessage, ChatSession
from app.schemas.models import ChatSessionDetail, ChatSessionResponse

class ChatSessionService:
    @staticmethod
    def _view(session: ChatSession) -> ChatSessionResponse:
        return ChatSessionResponse(
            id=session.id, user_id=session.user_id, title=session.title,
            metadata=session.metadata_ or {}, created_at=session.created_at,
            updated_at=session.updated_at, pending_run_id=session.pending_run_id,
        )

    async def list_for_user(self, db: AsyncSession, user_id: str) -> list[ChatSessionResponse]:
        rows = await db.execute(select(ChatSession).where(ChatSession.user_id == user_id)
            .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc()))
        return [self._view(row) for row in rows.scalars().all()]

    async def owned(self, db: AsyncSession, user_id: str, session_id: str) -> ChatSession:
        row = await db.scalar(select(ChatSession).where(
            ChatSession.id == session_id, ChatSession.user_id == user_id))
        if row is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        return row

    async def detail(self, db: AsyncSession, user_id: str, session_id: str) -> ChatSessionDetail:
        session = await self.owned(db, user_id, session_id)
        rows = await db.execute(select(ChatMessage).where(ChatMessage.session_id == session.id)
            .order_by(ChatMessage.id.asc()))
        return ChatSessionDetail(
            session_id=session.id,
            history=[(row.role, row.content) for row in rows.scalars().all()],
            pending_run_id=session.pending_run_id,
        )

    async def delete(self, db: AsyncSession, user_id: str, session_id: str) -> None:
        session = await self.owned(db, user_id, session_id)
        await db.delete(session)
        await db.commit()

    async def ensure(self, db: AsyncSession, user_id: str, session_id: str | None, title: str) -> ChatSession:
        if session_id is not None:
            return await self.owned(db, user_id, session_id)
        session = ChatSession(id=str(uuid4()), user_id=user_id, title=title[:255], metadata_={})
        db.add(session)
        await db.flush()
        return session

    async def append_turn(self, db: AsyncSession, session: ChatSession, query: str, answer: str) -> None:
        db.add(ChatMessage(session_id=session.id, role="user", content=query, metadata_={}))
        db.add(ChatMessage(session_id=session.id, role="assistant", content=answer, metadata_={}))
        await db.commit()

chat_session_service = ChatSessionService()
```

**整体解释：** 服务像只接受出示会员卡的档案管理员。`owned` 用 session_id 和 user_id 同时查“封面”；只有找到自己的封面才读取页或删除。列表按更新时间和 ID 排，避免同秒顺序不稳。历史按消息自增 ID 排，给前端它认识的 `(role, content)` 对。`ensure` 与 `append_turn` 先为第 36 篇准备：新会话先在同一事务 flush，回答成功后再把两条消息一起 commit；若现有会话 ID 属于别人立即 404。

**工程位置与触发时刻：** 本篇 HTTP 只调用 list/detail/delete；ensure 与 append_turn 第 36 篇才触发。

**完成这一小步的判断：** 双账号列表互不相见，历史顺序稳定，删除仅影响本人会话。

**如果这里失败：** 若 metadata 字段报错，查 _view 是否映射 metadata_；若外键报错，查 ensure 的 flush。

### 步骤 2：【新增文件】 `backend/app/router/chat_router.py`

**文件职责：** 提供前端现有会话 URL

**编辑文件的完整地址：**

```text
./backend/app/router/chat_router.py
```

**完整文件内容：**

```python
"""聊天会话 HTTP 接口；模型流将在后续步骤接入。"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.success_response import success_response
from app.db.db_config import get_db
from app.services.chat_session_service import chat_session_service
from app.utils.auth_utils import get_current_user_id

chat_router = APIRouter(prefix="/chat", tags=["chat"])

@chat_router.get("/sessions")
async def list_sessions(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return success_response(data={"sessions": await chat_session_service.list_for_user(db, user_id)})

@chat_router.get("/sessions/{path_user_id}")
async def list_user_sessions(
    path_user_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if path_user_id != user_id:
        raise HTTPException(status_code=403, detail="无权查看该用户会话")
    return success_response(data={"sessions": await chat_session_service.list_for_user(db, user_id)})

@chat_router.get("/session/{session_id}")
async def get_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return success_response(data=await chat_session_service.detail(db, user_id, session_id))

@chat_router.delete("/session/{session_id}")
async def delete_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await chat_session_service.delete(db, user_id, session_id)
    return success_response(message="会话已删除")
```

**整体解释：** 路由是接待窗口，不负责自己拼 SQL。列表 URL 中的 path_user_id 仅为兼容复制来的前端；它必须等于 JWT 得到的 user_id，否则 403，且服务仍只接受 JWT 的 ID。详情与删除统一调用 owned，未找到的他人会话和随机 ID 都 404。删除成功消息必须建立在数据库 commit 之后；不能先从前端列表移除就称作数据已清理。

**工程位置与触发时刻：** 前端 Sessions.tsx 发 GET/DELETE，AIChat.tsx 发 GET 详情。

**完成这一小步的判断：** OpenAPI 有四个会话接口；跨用户路径 403，跨用户 session_id 404。

**如果这里失败：** 若列表为空但数据库有行，检查 JWT user_id 和数据表 user_id 是否一致。

### 步骤 3：【修改】 `backend/main.py`

**文件职责：** 注册聊天路由组

**编辑文件的完整地址：**

```text
./backend/main.py
```

**修改定位与前后对照：** 搜索代码块中的原函数或配置项，按 `-` 删除旧行、按 `+` 增加新行。只展示本篇变更。

```diff
@@
 from app.router.review_router import review_router
+from app.router.chat_router import chat_router
@@
 app.include_router(review_router)
+app.include_router(chat_router)
 register_exception_handlers(app)
```

**整体解释：** 路由文件只是写好了规则，main.py include_router 才把它挂到应用。前端用 `/chat/...` 时会进入同一个 FastAPI、JWT 和统一错误处理环境。此时没有 `/chat/agent/query/stream`，聊天输入框仍不能得到回答；不要把会话 CRUD 的完成误写成整个 Agent 页面完成。

**工程位置与触发时刻：** 重载后应用注册 chat_router，访问 GET/DELETE 才执行数据库操作。

**完成这一小步的判断：** OpenAPI 可见 /chat/sessions 与 /chat/session/{id}。

**如果这里失败：** 如果出现 404，检查 main.py 的 include_router 和 Uvicorn 重载进程。

## 4. 请求和状态如何穿过这些文件

下面只追踪本篇真正涉及的调用链，帮助把刚改的文件连起来；这段解释不需要复制进源码。

1. **会话列表：** Sessions 页从用户状态取得 ID，调用 /chat/sessions/{id}。
2. **路径核对：** 路由先比较 path_user_id 与 JWT 用户，防止参数伪造。
3. **列表查询：** 服务以 JWT 用户过滤 ChatSession，按更新时间和 ID 排序。
4. **详情归属：** AIChat 页打开 /chat/session/{id}，服务先查拥有权。
5. **历史读取：** 只在拥有会话后查 ChatMessage，并按自增 ID 形成 history。
6. **删除：** 本人会话被 db.delete/commit；数据库级联清除消息。
7. **响应：** 统一 JSON 结构回前端；pending_run_id 当前为空。

**事务与隔离边界：** 本篇没有创建新会话的公开路由，因为复制来的前端是发送第一条消息时才得到 session_id。ensure 与 append_turn 为第 36 篇预备，但用户不能通过这两个 Python 方法绕过路由权限。会话删除只覆盖 MySQL；未来若加入 Agent 检查点、向量或图谱关联，删除流程需同步扩展。

## 5. 按阶段运行和验收

下列命令在复刻 `backend` 目录执行；另开终端保持 Uvicorn 运行。只有完成上面的文件步骤、且数据库/Redis 就绪后再执行。示例请求里的账号、令牌、笔记或文档 ID 应来自本机临时数据，不要复制真实用户资料。

```bash
cd "./backend"
uv run python -m compileall -q app main.py
uv run uvicorn main:app --reload --host 127.0.0.1 --port 8100
```

如果 8100 已有本项目服务在运行，只保留一份进程；改动 Python 文件后确认重载成功，再在另一终端请求 `/health/ready`。接下来的检查应逐个执行并观察 HTTP 状态、业务 `code`、MySQL 行数或事件序列，而不是只看命令退出码。

### 配套核验与设计依据

下面列出与本篇改动直接相关的已有文件、局部命令和验证意图；它们不占用文件编辑步骤。SQL 片段或含占位符的 HTTP 片段是核验思路，执行前必须换成当前测试数据与可运行命令。

**复核第 33 篇外键与元数据列**：`./backend/app/models/chat_history.py`。服务即将操作会话和消息，先确认模型用了相同 session_id 长度和统一 Base。尤其 metadata_ 是 Python 属性，响应 JSON 的 metadata 则是对外字段；如果服务直接把 ORM 字典丢出去，前端会收到 metadata_ 或内部 SQLAlchemy 状态。这里仅读现有结构，不新建表。

可用的定位或请求片段：

```bash
rg -n "class ChatSession|class ChatMessage|user_id|session_id|metadata_" backend/app/models/chat_history.py
```

观察点：能看到用户归属列与消息外键。 若不符合，若模型不一致，先修第 33 篇的结构，再写路由。

**核对历史响应字段对齐前端**：`./backend/app/schemas/models.py`。前端 sessionsApi.get 取的是 data.session_id 和 data.history，不是 `messages`。如果后端返回 ORM rows 的列表，页面不会自动理解；Pydantic 模型明确把数据库消息转成二维数组。pending_run_id 保留为 None，说明当前没有审批待恢复，不应制造假的 pending payload。

可用的定位或请求片段：

```bash
rg -n "class ChatSessionResponse|class ChatSessionDetail|history|pending_run_id" backend/app/schemas/models.py
```

观察点：history 是按顺序的 role/content 元组，JSON 编码后是数组。 若不符合，若页面历史为空，先看响应 data 结构和数据库是否真有消息。

**测试 URL 中伪造他人 user_id**：`./backend/app/router/chat_router.py`。路径参数看起来像用户 ID，却只是浏览器提供的字符串。用不匹配的值应得到 403，而不是替别人列会话。即使未来前端把当前 user_id 搞错，也不能通过删除这段判断来让页面“恢复”；应修正前端用户状态或后端令牌解析。

可用的定位或请求片段：

```bash
curl -i http://127.0.0.1:8100/chat/sessions/someone-else -H "Authorization: Bearer $RAG_TOKEN"
```

观察点：HTTP 403，数据库没有返回他人会话。 若不符合，若 200，检查比较使用的是 path_user_id 与 token user_id。

**空列表为合法结果**：`./backend/app/router/chat_router.py`。首次使用者没有会话，应该看到 `{sessions: []}`，而不是假造一条“新的对话”数据库行。列表页的“新建会话”按钮只导航到 `/chat`，第 36 篇在真正发送第一条消息时才创建会话。这样可以避免用户只是点进页面就留下大量空白会话。

可用的定位或请求片段：

```bash
curl -sS http://127.0.0.1:8100/chat/sessions -H "Authorization: Bearer $RAG_TOKEN" | python3 -m json.tool
```

观察点：空账号返回 200、data.sessions 空数组。 若不符合，如果请求会插入行，检查是否错误地在 list_for_user 中调用 ensure。

**用隔离临时会话验证消息读取顺序**：`./backend/app/services/chat_session_service.py`。第 36 篇之前可以在专用临时账号下用测试脚本插入一条会话、两条消息，再从 GET 详情确认 history 依序是 user、assistant。这里不建议手工插入到现有账号的真实会话。数据库查询只是一层证据，HTTP 还要确认归属检查发挥作用。

可用的定位或请求片段：

```sql
SELECT id,role,content FROM chat_messages WHERE session_id="<临时会话ID>" ORDER BY id;
```

观察点：history 与数据库 id 顺序一致。 若不符合，若顺序跳动，检查 order_by 是否只用了同秒 created_at。

**删除本人临时会话并确认外键清理**：`./backend/app/router/chat_router.py`。先确认 ID 是本篇专用测试会话，再发送 DELETE。响应成功后，详情 404，数据库对应 ChatMessage 行数为 0。换另一个账号 token 删除同一 ID 应 404 且原会话保留。这个顺序能独立验证权限与级联删除。

可用的定位或请求片段：

```text
DELETE /chat/session/<临时会话ID>
```

观察点：本人删除成功，别人不能删，消息无孤儿。 若不符合，若消息残留，检查 MySQL 真实外键，不只看 ORM 类。

### 验收 1：路由存在

**准备与操作：** 重载并查看 OpenAPI。

```text
GET /openapi.json
```

**期望结果：** 四条会话 GET/DELETE 路径可见。

**为什么要验这一项：** 避免把单纯导入文件当接入完成。

**不符合时从哪里查：** 看 include_router。

### 验收 2：匿名列表

**准备与操作：** 不带 JWT。

```text
GET /chat/sessions
```

**期望结果：** 401。

**为什么要验这一项：** 会话是私人数据。

**不符合时从哪里查：** 查路由 Depends。

### 验收 3：空列表

**准备与操作：** 专用新账号。

```text
GET /chat/sessions
```

**期望结果：** data.sessions=[]。

**为什么要验这一项：** 列表不制造会话。

**不符合时从哪里查：** 看 list_for_user 是否写库。

### 验收 4：路径用户伪造

**准备与操作：** token A 请求用户 B 的路径。

```text
GET /chat/sessions/<B_ID>
```

**期望结果：** 403。

**为什么要验这一项：** 路径不是身份。

**不符合时从哪里查：** 比较 path_user_id 与 token user_id。

### 验收 5：本人列表

**准备与操作：** A 有一条测试会话。

```text
GET /chat/sessions/<A_ID>
```

**期望结果：** 只含 A 会话。

**为什么要验这一项：** 验证过滤和排序。

**不符合时从哪里查：** 查 ChatSession.user_id 条件。

### 验收 6：他人详情

**准备与操作：** B token 查 A session_id。

```text
GET /chat/session/<A_SESSION_ID>
```

**期望结果：** 404。

**为什么要验这一项：** 不泄露他人会话存在性或消息。

**不符合时从哪里查：** 查 owned 方法。

### 验收 7：历史顺序

**准备与操作：** A 会话有 user、assistant 两条消息。

```text
GET /chat/session/<A_SESSION_ID>
```

**期望结果：** history 按 id 形成两项。

**为什么要验这一项：** 让聊天页能正确回放。

**不符合时从哪里查：** 查 ChatMessage.id 排序。

### 验收 8：他人删除

**准备与操作：** B token 删除 A 会话。

```text
DELETE /chat/session/<A_SESSION_ID>
```

**期望结果：** 404，A 会话仍在。

**为什么要验这一项：** 验证删除鉴权。

**不符合时从哪里查：** 查是否先 owned 再 delete。

### 验收 9：本人删除

**准备与操作：** A token 删除临时会话。

```text
DELETE /chat/session/<A_SESSION_ID>
```

**期望结果：** 成功；详情 404；消息计数为 0。

**为什么要验这一项：** 验收外键级联与事务。

**不符合时从哪里查：** 查数据库 DDL 与 commit。

### 验收 10：重复删除

**准备与操作：** 同一 ID 再删一次。

```text
DELETE /chat/session/<A_SESSION_ID>
```

**期望结果：** 404。

**为什么要验这一项：** 辨认资源已不存在的语义。

**不符合时从哪里查：** 若 200 假成功，检查服务是否跳过查找。

## 6. 深入动手与状态核对

### 三种路径不代表三种授权规则

前端会用 `/chat/sessions` 列表、`/chat/sessions/{user_id}` 带用户路径的列表、`/chat/session/{session_id}` 详情与删除。带在 URL 里的 user_id 是浏览器提供的普通字符串，不能代替令牌中的身份；后端先用 JWT 得到当前用户，再比较路径参数，不相等应 403。所有最终访问会话数据的查询都用 `ChatSession.user_id == token_user_id`。若路径中只有 session_id，也不能因此跳过归属条件。对不属于本人的 ID 返回 404，可避免泄露这个 ID 是否真实存在。

服务层的 `owned()` 是复用的权限闸门。列表只选择当前用户的封面；详情先通过 owned，再按消息 `id` 升序取历史；删除也先通过 owned，再删除父会话并提交。这样同一条权限规则同时覆盖 GET 和 DELETE，未来增加“追加消息”时也能重用。不能在路由里做一次 `owned()`，服务内部却改用只按 ID 的查询，因为复用位置一多就容易漏。数据库级联清理消息，而不是前端先循环删除每条历史。

### 响应映射和前端恢复

列表页用会话的 `id`、`title`、`updated_at` 等字段排序；同秒更新需要用 ID 作第二排序键，避免刷新后列表顺序来回跳。详情必须返回前端认识的 `session_id` 与 `history`，每个历史元素是按顺序的一对角色和内容。ORM 的 `metadata_` 要明确映射成响应的 `metadata`，不能把 SQLAlchemy 内部状态序列化出去。`pending_run_id=None` 只说明当前没有审批任务；前端的审批操作在本阶段仍不可用。

验证时给 A、B 各建一条临时会话，标题故意写相同。A 列表只能有 A ID，B 列表只能有 B ID。A 用 B 的 session_id 请求详情和删除，两者均应拒绝，B 的消息数量不变。随后 A 删除自己的 ID，详情变 404，相关消息归零，B 记录仍在。若列表返回空却详情有数据，先核对服务连接的数据库、`user_id` 与 JWT 的来源；不要通过删除用户过滤条件让页面“恢复”。

### 把会话访问规则落实到每条路径

`GET /chat/sessions` 没有路径 user_id，服务直接用 JWT 中的用户 ID 过滤。`GET /chat/sessions/{user_id}` 虽然多了一个参数，也不能让浏览器指定别人；先比较它与令牌身份，不一致就 403。`GET /chat/session/{session_id}` 与 DELETE 只有资源 ID，更必须用 owned 查询附带用户条件。这里的 403 与 404 有不同目的：路径明确声称要代表另一个用户时直接拒绝；资源详情用 404 不泄露是否存在另一个用户的会话。

列表响应不是把 ORM 对象原样返回。ORM 的 `metadata_` 是为了避开保留名，前端要的是 `metadata`。服务构造 `ChatSessionResponse` 时显式选出 id、user_id、title、创建/更新时间和可空的 `pending_run_id`。如果以后 metadata 放工具状态，也要审查其中是否含内部提示、调用参数或密钥，不能因为字段是 JSON 就整包暴露。当前 `pending_run_id=None` 的响应告诉前端没有待恢复运行，不代表后端已具备审批能力。

### 删除和多轮写入应如何相处

删除会话用按用户过滤的 SELECT 先拿到父行，再 `db.delete`、commit；MySQL 外键级联删除它的消息。若删除过程中有正在生成的聊天流，第 36 篇最后写入时会再次验证 owned，已删除会话应失败并发送 error，不应偷偷新建同 ID 会话把删除操作“撤销”。当前章节没有并发版本号或软删除，若产品需要可靠的“删除后绝不复活”，可把删除状态与写入在同一事务里锁定或设计版本字段。先把普通单请求行为验证清楚。

`ensure` 和 `append_turn` 在本篇先作为服务能力放入，但 HTTP 列表/详情/删除不会调用它们；空数据库里 GET sessions 返回空数组是正确结果。第 36 篇成功得到完整答案后，才通过 ensure 选择新建或复用会话，再通过 append_turn 一次保存 user/assistant 两条消息。不要为了让会话页面有东西而在 GET 里自动创建空白会话，那会让单纯浏览列表产生写入。

用 A、B 两个临时账号验收时，要同时观察“拒绝”和“无副作用”：B 传 A 的 session_id 删除得到 404，A 的会话与消息仍在；A 删除自己的 ID 后 A 详情变 404、消息归零，B 仍能读自己的会话。若 A 列表泄露 B 标题，即使详情还能阻止访问，也已发生隐私泄露。所有查询层都要包含用户范围。

### 对四条 URL 做一张真正可执行的权限矩阵

用两个临时账号 A、B，各自拥有一条会话和两条消息。A 调 `/chat/sessions` 与 `/chat/sessions/{A_ID}`，都应只见 A 的会话；A 调 `/chat/sessions/{B_ID}` 得 403。A 调 `/chat/session/{B_SESSION_ID}` 得 404，DELETE 同一 ID 也得 404，之后 B 仍能读取原本两条消息。再让 A 删除自己的会话，A 的详情应变 404，B 的会话仍然完整。矩阵要比较真实会话 ID，不只比较标题，因为两个人可以给会话取相同名称。

若从前端页面打开详情却显示空历史，按调用链定位：浏览器是否带 JWT，URL 的 session_id 是否正确，后端 owned 是否找到本人封面，`ChatMessage.session_id` 是否和封面 ID 相等，查询是否按 id 排序，响应是否叫 `data.history`。不要为了显示文字把服务改成“查不到本人封面就按 ID 全局查”，那会把展示问题变成越权问题。

列表与详情读请求原则上不应写入数据库；只有删除调用 commit，未来的聊天追加会写入。通过 MySQL 的消息计数可观察这一点：重复 GET 不增加、减少或重排消息；删本人父会话后相关计数归零。若使用 ORM 级联和数据库级联混合，要确认实际 SQL 不会造成额外不必要的逐条删除；当前模型未定义 relationship，数据库外键是主要清理路径。若旧表没有 `ON DELETE CASCADE`，DELETE 可能因子行存在而失败，不应在客户端悄悄忽略。

本篇 `ensure` 为第 36 篇预留新建会话的入口，但现有列表接口不会调用它。测试空用户列表返回 `[]`，不要把“自动出现一个新对话”当正确结果。`pending_run_id` 也只作为可空字段进入响应；任何审批或恢复按钮仍需等以后真实实现相关 API 和检查点存储。

### 会话排序要追踪“最后活动”真正来自哪里

列表若按 `ChatSession.updated_at DESC` 排序，新建时它有默认时间；删除不影响其他行；但向已有会话追加 ChatMessage 时，数据库不会因为子表 INSERT 自动更新父表的 `updated_at`。第 36 篇如果希望刚回复的会话升到顶部，就需要在同一写事务中显式触碰父行。当前教程应把这个验收点记录为待补机制，不能因为 SQL 写了 order_by 就宣称“最近聊天总在顶部”。这也能帮助面试时解释：排序规则、字段更新来源和触发时机必须一起设计。

详情历史的顺序用消息自增 ID，而不是 role 分组。`history=[(row.role,row.content) ...]` 经过 JSON 序列化成为二维数组，前端按 user/assistant 顺序回放。若某次写入只有 user 没有 assistant，页面可能出现未配对问题；第 36 篇一次提交两条消息降低这种半成品。若未来保存工具消息，role 的取值与前端展示都要扩展，不能让 UI 把 tool 输出当成人类回答。现在的 ChatMessageResponse 虽有独立结构，详情实际选择 `history` 契约，这是复制前端所需格式。

需要区分 403 与 404 的可观测条件：`/sessions/{user_id}` 的路径身份与 token 不同，明确拒绝代表他人查询，返回 403；单个 session_id 不存在或属于他人，统一 404，不泄露是否存在。若开发中发现前端总拿错 userId，应修前端登录状态或服务端返回的 profile，不应在后端删掉比较来让页面“能用”。相同原则也适用于 DELETE，尤其不能因为删除没有响应体就放松授权。

## 7. 工程面试思考

回答时要指向本篇具体文件、数据库约束或接口结果，区分当前已实现、验证时才可能观察到的结果与未来扩展。这里讨论设计判断，不背诵通用定义。

**面试官：为什么路由允许 /sessions/{user_id} 却又比对 token？**

它是为了兼容已有前端 URL，而不是信任客户端指定用户。真正授权信息来自 JWT；若两者不一致，拒绝请求比悄悄忽略参数更容易发现前端状态错误。

**面试官：删除会话为什么先查拥有权，不能直接 DELETE WHERE id=?**

直接按 id 删除会让知道会话 ID 的人删除别人数据；即使 ID 难猜，它也不是权限机制。owned 先限定 id+user_id，再删除，数据库级联只负责子消息清理。

**面试官：会话很多时全量列表有什么问题？**

当前实现返回全部本人会话。数量增长后应增加分页、稳定游标或 limit，并以 user_id+updated_at 索引验证查询计划；前端也要支持加载更多。不能只给 SQL 加 LIMIT 却继续把 total_count 当全部数量。

**面试官：回答生成中用户删除会话会怎样？**

第 36 篇写回答前需要再次确认会话状态，或者用事务/版本条件决定是否写入。当前 CRUD 与尚未实现的流并发时需明确冲突语义；不能让后台写入复活已删除会话。

## 8. 常见故障的定位顺序

- **列表空：** 核对 token 用户 ID、表 user_id、是否还没发第一条消息。
- **403：** 前端路径中的 userId 与 JWT 不一致，刷新用户状态。
- **详情 404：** 资源不存在或不属于当前用户；不要改成按 ID 全局查。
- **历史乱序：** 使用消息自增 id 排序。
- **删除后有残留：** 检查真实 MySQL 外键 ondelete。

## 9. 本篇边界和下一篇

本篇会话列表与历史读取已经有真实数据库来源；聊天回答仍未接通。第 35 篇先构造限定当前用户的知识检索上下文，第 36 篇才把它与 DeepSeek 流式响应合并。

本篇没有修改前端文件。新代码完成并经过你本机的验证后，才把它记为你亲手完成；仅阅读教程、助手先前的隔离检查或接口文档出现新路径，都不能代替真实执行。
