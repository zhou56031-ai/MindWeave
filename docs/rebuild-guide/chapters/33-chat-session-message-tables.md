# 第 33 篇：聊天会话与消息表的持久化骨架

> 前置：第 32 篇完成后的复刻后端。本文是待操作教程，写作时对照了正式复刻目录和参考项目；文中的预期结果不是正式工程已实测的结果。
> 成果：MySQL 建立 chat_sessions 和 chat_messages，字段与前端会话列表、历史恢复所需结构对齐。
> 范围：只指导后端；前端继续直接使用已经复制的源码。新增文件给完整代码，修改文件只给本次 diff，不重复整份最终源码。

## 1. 本篇要接通的真实能力

前端聊天页面可以在路由 `/chat/:id` 打开旧会话；如果后端只把 messages 放在 Python 列表，重启后历史就丢失。参考项目用 chat_sessions 与 chat_messages 保存会话及消息，本篇先建立统一 Base 下的两张表和响应模型，下一篇才开列表/详情/删除接口。聊天持久化必须先回答“消息属于哪个用户的哪个会话”，再讨论模型怎么说话。

本篇从复刻项目现有代码继续，路径和导入均从下面这个固定目录算起。不要在参考仓库执行修改；那份源码用于比较接口与数据流。代码注释中【新增】标出本步新行为，diff 的正负号只用于定位，不要粘进 Python 文件。涉及账号或模型密钥时只用本机 `.env`，不把真实值写进教程或 Git。

**复刻根目录：**

```text
.
```

**本篇接口或产物契约：**

- chat_sessions 有 id、user_id、title、metadata、pending_run_id、created_at、updated_at。
- chat_messages 有自增 id、session_id、role、content、metadata、created_at，外键指向 chat_sessions。
- 同一会话消息按自增 id 顺序读取，删除会话时清理其消息。
- 会话 ID 是不透明字符串，用户身份始终从 JWT 确认；本篇只建表，不新增 HTTP 接口。

**本篇与参考实现的差异：** 参考仓库的 chat_history.py 自建另一份 declarative_base；复刻项目已有统一 Base.metadata，本篇把聊天表登记到同一套生命周期，避免启动时漏建表。

**技术路线阅读：** 数据库与 ORM 选型继续参见 [Q05](technology-routes/Q05-mysql-relational-database.md) 和 [Q06](technology-routes/Q06-sqlalchemy-async-orm.md)。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 路径 | 本步职责 |
|---:|---|---|---|
| 1 | 【新增文件】 | `backend/app/models/chat_history.py` | 定义当前用户会话与会话内消息 |
| 2 | 【修改】 | `backend/app/db/db_config.py` | 把聊天表加入启动建表清单 |
| 3 | 【修改】 | `backend/app/schemas/models.py` | 给会话列表、消息和详情准备响应模型 |

先看清楚上表：新文件的父目录若已存在就复用；步骤之间的 import 按顺序出现。每做完一个文件就做该步的小检查，不要把所有代码贴完才第一次启动。修改已有文件时请按 diff 的上下文搜索函数名或配置项，行号只供参考，因为上一章或你自己的改动可能改变行号。

## 3. 按顺序修改文件与验证

### 步骤 1：【新增文件】 `backend/app/models/chat_history.py`

**文件职责：** 定义当前用户会话与会话内消息

**编辑文件的完整地址：**

```text
./backend/app/models/chat_history.py
```

**完整文件内容：**

```python
"""聊天会话和消息表，复用应用统一 Base。"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, func
from app.models.base import Base

class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), index=True, nullable=False)
    title = Column(String(255), default="新的对话", nullable=False)
    pending_run_id = Column(String(64), nullable=True)
    metadata_ = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(), server_default=func.now(), onupdate=func.now(), nullable=False)

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True, nullable=False)
    role = Column(String(32), nullable=False)
    content = Column(Text, nullable=False)
    metadata_ = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime(), server_default=func.now(), nullable=False)
```

**整体解释：** 会话表像一本聊天记录册的封面，消息表是按顺序装订的每页内容。封面写归属 user_id；消息只保存 session_id，因为权限查询会先验证封面再读消息。`metadata_` 是 Python 属性名，对应数据库列仍叫 metadata，避开 SQLAlchemy declarative API 的保留名。`ON DELETE CASCADE` 让删除封面时数据库清除页，但服务层仍须先按 user_id 验证封面，不能直接按任意 session_id 删除。

**工程位置与触发时刻：** 导入两个类只登记结构，启动建表后 MySQL 才真正出现表。

**完成这一小步的判断：** 两个表有外键、时间字段和统一 Base；文件编译通过。

**如果这里失败：** 若定义属性 metadata 触发 SQLAlchemy 错误，改回 metadata_ 的映射写法。

### 步骤 2：【修改】 `backend/app/db/db_config.py`

**文件职责：** 把聊天表加入启动建表清单

**编辑文件的完整地址：**

```text
./backend/app/db/db_config.py
```

**修改定位与前后对照：** 搜索代码块中的原函数或配置项，按 `-` 删除旧行、按 `+` 增加新行。只展示本篇变更。

```diff
@@ async def init_db() -> None:
     from app.models.review_record import ReviewRecord  # noqa: F401
+    from app.models.chat_history import ChatSession, ChatMessage  # noqa: F401

     async with async_engine.begin() as connection:
```

**整体解释：** 这一步不是执行建表命令本身，而是告诉 Base.metadata：还要检查 chat_sessions 和 chat_messages 两张表。启动时 create_all 先建父表，再建依赖外键的消息表。它只建立缺失表，不会给既有表自动加列；未来修改 schema 要迁移。

**工程位置与触发时刻：** Uvicorn 加载应用进入 lifespan 后触发 init_db。

**完成这一小步的判断：** 启动无外键错误，两张表在复刻 MySQL 中可见。

**如果这里失败：** 若消息表先建导致外键错误，确认两个类使用同一个 Base 并正确声明 ForeignKey。

### 步骤 3：【修改】 `backend/app/schemas/models.py`

**文件职责：** 给会话列表、消息和详情准备响应模型

**编辑文件的完整地址：**

```text
./backend/app/schemas/models.py
```

**修改定位与前后对照：** 搜索代码块中的原函数或配置项，按 `-` 删除旧行、按 `+` 增加新行。只展示本篇变更。

```diff
@@
 class AutoTagResponse(BaseModel):
     note_id: str
     tags: list[str]
+
+
+class ChatSessionResponse(BaseModel):
+    id: str
+    user_id: str
+    title: str
+    metadata: dict = Field(default_factory=dict)
+    created_at: datetime
+    updated_at: datetime
+    pending_run_id: str | None = None
+
+
+class ChatMessageResponse(BaseModel):
+    id: int
+    session_id: str
+    role: str
+    content: str
+    metadata: dict = Field(default_factory=dict)
+    created_at: datetime
+
+
+class ChatSessionDetail(BaseModel):
+    session_id: str
+    history: list[tuple[str, str]]
+    pending_run_id: str | None = None
```

**整体解释：** ORM 对象是数据库内部表示，API 响应是给浏览器的合同。会话列表显示 id、标题和时间，历史详情按前端 sessionsApi.get 期待的 `history: [role, content][]` 组织。metadata_ 在数据库模型里避开保留名，响应对外叫 metadata；不要直接 model_validate ORM 指望字段自己改名，下一篇服务要显式映射。pending_run_id 先预留，审批/恢复未实现时保持 None。

**工程位置与触发时刻：** 第 34 篇服务查询成功后构造这些响应模型；本章只定义，不产生数据。

**完成这一小步的判断：** Pydantic 可以构造合法会话/消息/详情对象。

**如果这里失败：** 若前端不识别 history，检查字段是否被误叫 messages。

## 4. 请求和状态如何穿过这些文件

下面只追踪本篇真正涉及的调用链，帮助把刚改的文件连起来；这段解释不需要复制进源码。

1. **数据归属：** chat_sessions.user_id 标明会话拥有者。
2. **消息关联：** chat_messages.session_id 外键指向会话主键。
3. **建表：** init_db 导入两个模型，Base.metadata.create_all 建立缺失表。
4. **列表契约：** ChatSessionResponse 把 metadata_ 映射为 metadata、提供时间和 pending_run_id。
5. **历史契约：** ChatSessionDetail 把有序消息映射成前端期待的 history 数组。
6. **删除规则：** 数据库有级联，但 HTTP 服务仍需先确认用户有权删除会话。

**事务与隔离边界：** MySQL 外键只保证消息所属会话存在，不能自动验证“请求用户有权读消息”；用户隔离由第 34 篇服务查询会话时完成。这个版本的 Text 字段适合当前短消息；长篇输出、附件与工具调用需要按实际大小和查询方式再设计。pending_run_id 目前只是字段，不代表已经有审批恢复能力。

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

**确认所有表应共用同一 Base**：`./backend/app/models/base.py`。Base.metadata 是启动时建表的唯一清单。如果聊天模型另建 declarative_base，已有 init_db.create_all 不会看见新表；代码 import 也可能正常，直到第一个聊天请求才报表不存在。先阅读 Base 文件，理解为何不能原样复制参考仓库的另一份 Base。

可用的定位或请求片段：

```bash
cat backend/app/models/base.py
```

观察点：看到已有 Base 定义，后续新模型从这里导入。 若不符合，若 Base 文件不在该路径，检查是否进入参考仓库。

**确认 init_db 统一导入模型**：`./backend/app/db/db_config.py`。`create_all` 像按照图纸清单检查施工。聊天模型必须在 run_sync(Base.metadata.create_all) 前导入，否则新表不在清单里。检查已有 Note、KnowledgeDocument、ReviewRecord 的导入位置，下一步照此加入。

可用的定位或请求片段：

```bash
rg -n "async def init_db|from app.models|create_all" backend/app/db/db_config.py
```

观察点：确认建表清单位置。 若不符合，如果服务运行时没有调用 init_db，先检查 lifespan，而非手工建表。

**确认建表早于服务接收请求**：`./backend/app/core/lifespan.py`。因为聊天表是新表，启动顺序不能靠“第一次聊天请求自动建”。lifespan 中 init_db 应在 yield 之前，表示应用开门前已准备好数据库结构。失败时明确启动失败，不让前端列表偶尔拿 500、偶尔拿空数组。

可用的定位或请求片段：

```bash
rg -n "await init_db|yield" backend/app/core/lifespan.py
```

观察点：init_db 在 yield 前。 若不符合，如果 startup 没运行，检查 main.py 的 FastAPI(lifespan=lifespan)。

**静态编译与模型导入**：`./backend/app/models/chat_history.py`。此命令只证明 Python 文件能解析。接着可导入 ChatSession、ChatMessage，检查它们的 Base.metadata.tables 是否同时包含两个表。不要因为 compileall 没输出就声称真实 MySQL 已创建，也不要把旧参考数据库的表当作复刻成果。

可用的定位或请求片段：

```bash
uv run python -m compileall -q app/models/chat_history.py app/schemas/models.py
```

观察点：无语法异常，Base.metadata 可见两表。 若不符合，若导入时报同名表重复注册，检查是否误复制另一份 Base 或重复定义类。

**观察真实 MySQL 的父子表和外键**：`./backend/app/db/db_config.py`。启动后用复刻 MySQL 账号只读查看表结构，确认 chat_messages.session_id 的外键指向 chat_sessions.id，on delete cascade 存在。此查询不应暴露消息内容，只看 schema。若是已有旧表，create_all 不会替它修外键，必须先记录并设计迁移。

可用的定位或请求片段：

```sql
SHOW CREATE TABLE chat_messages;
```

观察点：能读到外键与索引。 若不符合，如果表在参考库而复刻库没有，检查连接 URL 和 Compose 端口。

**检查数据库不会接受孤儿消息**：`./backend/app/models/chat_history.py`。只在专用测试数据库/事务中尝试外键失败；这条 SQL 的意义是验证消息页不能脱离封面存在。若数据库允许插入，外键可能没有建立、存储引擎不一致或旧表结构未迁移。不要在包含真实会话的库里反复插入垃圾数据。

可用的定位或请求片段：

```sql
INSERT INTO chat_messages(session_id,role,content) VALUES ("not-a-session","user","test");
```

观察点：应触发外键错误且没有行落库。 若不符合，若成功，立即在测试库清理并检查 SHOW CREATE TABLE。

### 验收 1：确认统一 Base

**准备与操作：** 导入三张表的模型。

```python
from app.models.base import Base
```

**期望结果：** chat_sessions 与 chat_messages 在同一 metadata。

**为什么要验这一项：** 避免参考源码另一份 Base 造成漏建。

**不符合时从哪里查：** 看模型 import 路径。

### 验收 2：编译

**准备与操作：** 检查新模型与 schema。

```bash
uv run python -m compileall -q app main.py
```

**期望结果：** 无异常。

**为什么要验这一项：** 先抓语法与导入问题。

**不符合时从哪里查：** 按 traceback 回到文件步骤。

### 验收 3：启动

**准备与操作：** 重载 Uvicorn。

```text
GET /health/ready
```

**期望结果：** 仍为 200。

**为什么要验这一项：** 新增表不应破坏原有依赖。

**不符合时从哪里查：** 查 startup 日志和 MySQL 权限。

### 验收 4：两表存在

**准备与操作：** 查询复刻 MySQL。

```sql
SHOW TABLES LIKE "chat_%";
```

**期望结果：** 两表均出现。

**为什么要验这一项：** 确认建表清单生效。

**不符合时从哪里查：** 检查 init_db import。

### 验收 5：外键

**准备与操作：** 查看消息表 DDL。

```sql
SHOW CREATE TABLE chat_messages;
```

**期望结果：** session_id 外键指向 chat_sessions。

**为什么要验这一项：** 防止孤儿消息。

**不符合时从哪里查：** 旧表需迁移，create_all 不加约束。

### 验收 6：级联

**准备与操作：** 在专用临时会话上验证删除。

```sql
DELETE FROM chat_sessions WHERE id="<测试ID>";
```

**期望结果：** 对应测试消息归零。

**为什么要验这一项：** 数据库删除约束真实生效。

**不符合时从哪里查：** 先确认测试 ID，不得删用户会话。

### 验收 7：metadata 名称

**准备与操作：** 构造临时模型对象。

```python
ChatSession(metadata_={"source":"test"})
```

**期望结果：** 数据库列名仍是 metadata。

**为什么要验这一项：** 区分 Python 保留名与 API 字段。

**不符合时从哪里查：** 看 Column("metadata", JSON)。

### 验收 8：历史顺序

**准备与操作：** 插入两条测试消息。

```sql
SELECT id,role,content FROM chat_messages WHERE session_id="<测试ID>" ORDER BY id;
```

**期望结果：** user、assistant 按 id 顺序。

**为什么要验这一项：** 下一篇历史回放需要稳定顺序。

**不符合时从哪里查：** 不要按 created_at 单独排序同秒记录。

### 验收 9：用户范围

**准备与操作：** 两用户各插入测试会话。

```sql
SELECT id,user_id FROM chat_sessions WHERE user_id="<用户ID>";
```

**期望结果：** 各自只见自己的会话行。

**为什么要验这一项：** 为 API 级用户隔离准备数据。

**不符合时从哪里查：** SQL 查本账号，勿导出其他用户内容。

### 验收 10：清理

**准备与操作：** 删除专用测试会话。

```sql
DELETE FROM chat_sessions WHERE id="<测试ID>";
```

**期望结果：** 测试消息被级联清理。

**为什么要验这一项：** 保持正式库整洁。

**不符合时从哪里查：** 限定主键，不运行全表 DELETE。

## 6. 深入动手与状态核对

### 先建好归属关系，再给聊天加“智能”

聊天页面刷新后要恢复历史，必须有一个不随进程重启消失的会话编号。`chat_sessions` 保存封面：ID、用户归属、标题、创建与更新时间；`chat_messages` 保存每页内容：所属 session_id、角色、文字、创建时间。消息表没有 user_id，这不是允许跨用户读取；服务必须先按 `ChatSession.id` 与 `ChatSession.user_id` 验证封面，再按 session_id 取页。只凭消息 ID 或 session_id 直接读消息会绕过用户隔离。数据库外键只证明会话存在，不会替 HTTP 层判断谁有权访问。

两个表都从同一 `Base` 继承，才能让当前 `init_db` 的 `Base.metadata.create_all` 看到它们。导入类好比把图纸放进一份清单；启动执行 create_all 才在缺表时建物理表。若复制参考仓库中另一份 `declarative_base()`，Python import 可能照样成功，但那两张图纸不在现有清单，启动后仍无聊天表。相反，如果库里早有同名旧表，create_all 不会为它补外键或新增列，需要独立迁移。要用真实 MySQL 的 DDL 证明父子关系，不把模型源代码等同于已生效约束。

`metadata` 在 SQLAlchemy 声明式模型里是保留含义，所以 Python 属性写 `metadata_`，通过 `Column("metadata", JSON)` 映射到数据库列。API 对外仍可以叫 `metadata`，但服务需要显式转译，不能把 ORM 对象粗暴转成 dict 交给前端。`pending_run_id` 在这个阶段只是可空字段：它方便将来接审批/恢复，不代表已经有运行检查点。把 `None` 返回给前端比伪造一个待审批 ID 更诚实。

### 可用数据库事实核对表设计

重启后先确认 MySQL 出现两张表，再读 `SHOW CREATE TABLE chat_messages`，检查 `session_id` 外键、索引和 `ON DELETE CASCADE`。用专用临时会话写两条消息，按消息自增 `id` 排序应稳定得到 user、assistant；不要只按同秒的 created_at 排序，因为同一秒里顺序可能无法判定。删除临时父会话后，子消息应消失；这项只在专用测试 ID 上执行。尝试孤儿消息只能在测试事务里做，预期是外键拒绝，不应污染真实学习记录。

如果未来要保存工具调用、附件、大段流式草稿，当前单一 Text 字段不够表达所有状态。不要先往 `metadata` 里随意塞不可追踪的业务字段；应明确每条消息的角色、状态、版本与大小限制。当前教程只为第 34 篇列表/详情/删除和第 36 篇成功问答保存铺好最小结构。

### 关系表设计的三层保证

第一层是模型声明：`ChatMessage.session_id` 写了 `ForeignKey("chat_sessions.id", ondelete="CASCADE")`。它告诉 SQLAlchemy 建表时需要父子关系，却不能证明已经存在的库被改好了。第二层是真实 MySQL DDL：`SHOW CREATE TABLE` 里必须出现外键与级联。第三层是行为：在专用临时会话插入消息后删除父会话，子消息归零。三层证据覆盖“源码有意图”“数据库有约束”“实际删除有效”；只做其中一层，都可能漏掉旧表、错库或启动没跑 `init_db` 的问题。

用户隔离是另一层，不能由外键替代。外键保证 `session_id` 指向某个会话，但 B 用户依然可能猜到 A 会话 ID；数据库并不知道当前 HTTP 令牌是谁。第 34 篇的服务必须先查 `ChatSession.id == session_id` 且 `ChatSession.user_id == token_user_id`，再读或删消息。就算 UUID 难猜，也不能把“不容易猜到”当权限设计。为了未来审计，也可以考虑给消息表冗余 user_id 并加复合约束，但那会增加写入一致性负担，当前阶段用父会话授权足够清晰。

自增消息 ID 是会话内恢复顺序的依据。数据库 `created_at` 通常不是唯一值，同一秒或同一毫秒内两条消息可能并列；单按时间排序的历史会偶尔颠倒。按 `id ASC` 读可以稳定回放。但自增 ID 不表达用户问答的语义配对，也不能单独说明流式回答是否成功；第 36 篇一次提交 user/assistant 两行来维持最小配对。若后续要记录失败草稿和工具事件，应增加显式 run 状态或消息类型，而不是把半成品也标成普通 assistant 消息。

### 新旧数据库状态不一致时的处置

若模型导入失败并提示 `metadata` 是保留属性，不要改数据库列名来绕过；Python 属性用 `metadata_`，真实列继续叫 `metadata`，响应服务显式映射。若 MySQL 已有同名聊天表但少字段，`create_all` 不会自动修改它，重启十次也没用。先备份与记录 DDL，再用版本化迁移增列、补默认值和约束；不要删掉用户历史重建表。教程中的建表方式适合从当前复刻库新增缺失表，不能代替长期升级流程。

若服务启动时表不存在，按顺序定位：导入类是否继承同一 `Base`，`init_db` 是否在 `create_all` 前 import 两个类，FastAPI 的 `lifespan` 是否在 yield 前调用 `init_db`，连接 URL 是否指向复刻 MySQL。最后才检查数据库账号权限。编译通过只说明 Python 语法正确；它既不触发 lifespan，也不执行 CREATE TABLE。把这几个时刻区分清楚，能避免“文件已经写了为什么库没有表”的困惑。

### 用元数据与真实 DDL 分别核实“同一张图纸”

在复刻 backend 执行 `uv run python -c 'from app.models.chat_history import ChatSession,ChatMessage; from app.models.base import Base; print(sorted(Base.metadata.tables))'`，应能在同一个列表里看到 `chat_sessions`、`chat_messages` 和已有 `notes`。这说明 Python 类已登记在同一份 metadata，但仍不说明 MySQL 已经执行建表。重启后端后再用复刻数据库账户查询 `SHOW TABLES LIKE "chat_%"` 和 `SHOW CREATE TABLE chat_messages`，比对表名、列类型与外键。两个检查发生在不同阶段，不能互相替代。

父表 `chat_sessions` 的 `user_id` 应有索引，因为会话列表总是按用户范围读；子表 `chat_messages.session_id` 应有索引，因为详情按会话取历史和删除父行时数据库需要找到子行。索引是否足够还要结合实际数据量与查询计划，当前并不需要提前建立很多组合索引。`updated_at` 用于列表排序，新增消息时是否自动更新父会话要看第 34/36 篇的具体写入；仅在 ChatSession 列上写 `onupdate`，并不意味着插入 ChatMessage 会自动触发父表 UPDATE。这个细节关系到多轮聊天后会话能否浮到列表顶部。

如果希望“最近有新消息的会话排最前”，第 36 篇 `append_turn` 需要显式更新父会话的 updated_at，或者使用单独的最后活动时间字段。不能只靠消息表插入时的 server_default；它不会传播到父行。文档当前的最小实现应在验收中检查这一点，若前端列表不重排，就把它列为下一次具体改动，而不是宣称“排序按更新时间已经完整”。

存储限制也要看实际数据库方言。MySQL `Text` 列有大小边界，模型输出若无界可能超过它；第 36 篇对回答字符数加限制是第一道防线，但中文 UTF-8 字节数与字符数不同，生产版应按数据库列能力和模型输出上限设更可靠的预算。`metadata` JSON 字段适合少量结构化附加信息，不适合堆放完整提示词、文档全文或密钥。消息历史属于私人数据，备份、日志和导出也需遵守用户隔离。

### 从第一次消息写入倒推表为何这样拆

假设用户问“解释事务”，助手回答两段。会话封面只有一行：它标识用户、标题和更新时间；消息表增加两行：role=user 的问题和 role=assistant 的完整答案。第二轮仍复用同一封面，再追加两行。若把所有历史塞进 ChatSession 的一个 JSON 列，每次新增都要重写越来越大的数组，按角色或时间读取一段也更麻烦。分表让消息可增量插入、按 ID 排序和独立限制大小，代价是详情要多一次查询或 JOIN。当前参考项目本来就有会话与消息概念，这种拆分贴合 1:1 目标。

删除操作与权限判断也因此有清楚次序：根据 JWT 的用户 ID 找封面，只有找到本人封面才请求删除；数据库外键负责移除消息页。若直接 `DELETE FROM chat_messages WHERE session_id = ?`，绕开父会话的 user_id，猜到 ID 就可能删别人历史。若先按 session_id 删除父行却忘记带 user_id 条件，同样越权。下一篇服务统一用 owned 作为读取、删除和后续写入的入口，就是为了让这个次序不容易漏。

`metadata_` 的名称不一致值得亲手验证。Python 访问 `session.metadata_`，SQL 表列叫 `metadata`，返回 JSON 要叫 `metadata`；三处名字不是同一个层的承诺。若在 Pydantic 响应里直接使用 `model_validate(session)`，没有配置属性映射时可能报缺字段或得到不想暴露的内部对象。第 34 篇会显式构造响应，这个映射应当能在测试样本里观察到。`pending_run_id` 目前存 NULL，不能因为有列就让前端显示可恢复审批；真实检查点还需更复杂的运行状态。

## 7. 工程面试思考

回答时要指向本篇具体文件、数据库约束或接口结果，区分当前已实现、验证时才可能观察到的结果与未来扩展。这里讨论设计判断，不背诵通用定义。

**面试官：为什么不把整个聊天记录塞进 chat_sessions 的一个 JSON 字段？**

逐条消息建表便于按顺序追加、分页、审计单条角色和内容，并避免每轮对话重写一个越来越大的 JSON。代价是查询历史多一次关联和更多行，后续可按 session_id 建索引及分页。

**面试官：数据库有 ON DELETE CASCADE，是否可以跳过鉴权？**

不能。级联只决定删父会话之后如何处理子消息，不决定请求方有没有资格删父会话。服务必须先用 session_id+user_id 查到会话，再执行删除。

**面试官：为什么统一 Base.metadata？**

已有 lifespan 只对 app.models.base.Base 做 create_all。另起一份 Base 会让聊天表不在这份 metadata 中，静态 import 可能通过，启动后却没有表。统一 Base 保证一个建表入口，但未来结构变更仍需要迁移。

**面试官：高并发聊天消息排序如何保证？**

当前用 MySQL 自增 id 作为单会话消息的稳定读取顺序。若需要严格的对话轮次和并发写入控制，可增加 session 内 seq 和唯一约束，并在写入时锁会话行；只靠秒级 created_at 无法稳定区分同秒消息。

## 8. 常见故障的定位顺序

- **表未创建：** 查 init_db 导入和启动日志。
- **metadata 报保留字：** Python 属性写 metadata_，Column 名称仍 metadata。
- **外键失败：** 先建 ChatSession 父行并 flush，再写 ChatMessage。
- **删会话后消息残留：** 核对真实 MySQL 外键 DDL，不只看模型。
- **历史顺序跳动：** 读取时按 ChatMessage.id 排序。

## 9. 本篇边界和下一篇

这两张表只是持久化骨架。第 34 篇提供与复制前端契约一致的会话列表、详情和删除接口，并把用户范围放到每个查询。

本篇没有修改前端文件。新代码完成并经过你本机的验证后，才把它记为你亲手完成；仅阅读教程、助手先前的隔离检查或接口文档出现新路径，都不能代替真实执行。
