# 第 27 篇：回顾记录表与笔记创建的同一事务

> 前置：第 26 篇完成后的复刻后端。本文是待操作教程，写作时对照了正式复刻目录和参考项目；文中的预期结果不是正式工程已实测的结果。
> 成果：每创建一篇笔记，同时生成一条归属同一用户、次日到期的回顾记录；删除笔记时 MySQL 清理它的回顾记录。
> 范围：只指导后端；前端继续直接使用已经复制的源码。新增文件给完整代码，修改文件只给本次 diff，不重复整份最终源码。

## 1. 本篇要接通的真实能力

参考项目的回顾功能依赖 review_records：它不直接把“明天要复习”写进笔记正文，而是给笔记配一条独立的进度记录。前端在回顾页读取 /review/today；本篇先把数据起点做实，第 28 篇才开放今日列表。我们把新笔记和回顾记录放进同一事务，避免页面已经看到笔记，却永远没有提醒。已有笔记不会因为新建表而自动补一条记录；这点要在验收时明确，而不是把空的历史数据误判为逻辑失效。

本篇从复刻项目现有代码继续，路径和导入均从下面这个固定目录算起。不要在参考仓库执行修改；那份源码用于比较接口与数据流。代码注释中【新增】标出本步新行为，diff 的正负号只用于定位，不要粘进 Python 文件。涉及账号或模型密钥时只用本机 `.env`，不把真实值写进教程或 Git。

**复刻根目录：**

```text
.
```

**本篇接口或产物契约：**

- `review_records.note_id` 指向 `notes.id`，`user_id` 来自已验证的 JWT，不接受客户端提供。
- 一个用户的一篇笔记至多一条回顾记录，由数据库唯一键保护。
- 创建笔记成功时两张表都有行；创建失败时两张表均不应留下半成品。
- 删除笔记后，外键级联清理对应回顾记录；本篇不新增对外回顾路由。

**本篇与参考实现的差异：** 参考实现把回顾记录与 AI 自动标签放进后续异步流程；教学阶段先同步建立最小的回顾行，以验证事务和外键。AI 题目与标签在后续章节加入。

**技术路线阅读：** [Q14：固定间隔回顾与其他调度路线](technology-routes/Q14-spaced-review-schedule.md)。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 路径 | 本步职责 |
|---:|---|---|---|
| 1 | 【新增文件】 | `backend/app/models/review_record.py` | 定义回顾记录的表结构、外键和唯一键 |
| 2 | 【新增文件】 | `backend/app/services/review_schedule.py` | 集中保存初始回顾时间与后续可复用的间隔规则 |
| 3 | 【修改】 | `backend/app/db/db_config.py` | 把回顾模型加入建表清单 |
| 4 | 【修改】 | `backend/app/services/note_service.py` | 让新笔记和初始回顾记录在同一事务提交 |

先看清楚上表：新文件的父目录若已存在就复用；步骤之间的 import 按顺序出现。每做完一个文件就做该步的小检查，不要把所有代码贴完才第一次启动。修改已有文件时请按 diff 的上下文搜索函数名或配置项，行号只供参考，因为上一章或你自己的改动可能改变行号。

## 3. 按顺序修改文件与验证

### 步骤 1：【新增文件】 `backend/app/models/review_record.py`

**文件职责：** 定义回顾记录的表结构、外键和唯一键

**编辑文件的完整地址：**

```text
./backend/app/models/review_record.py
```

**完整文件内容：**

```python
"""每篇笔记的回顾进度；当前阶段由笔记创建事务建立。"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from app.models.base import Base

class ReviewRecord(Base):
    __tablename__ = "review_records"
    __table_args__ = (UniqueConstraint("user_id", "note_id", name="uq_review_user_note"),)

    id = Column(String(36), primary_key=True)
    note_id = Column(String(36), ForeignKey("notes.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id = Column(String(36), index=True, nullable=False)
    last_reviewed_at = Column(DateTime(), nullable=True)
    review_count = Column(Integer, default=0, nullable=False)
    next_review_at = Column(DateTime(), nullable=False)
    interval_days = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime(), server_default=func.now(), nullable=False)
```

**整体解释：** 这张表不是存笔记内容的第二份副本，而是保存“同一篇笔记已经复习几次、上次何时复习、下一次何时到期”。把书和借阅卡分开，笔记正文改动不会抹掉学习进度。数据库外键负责确认 note_id 对应一篇真实笔记；唯一键阻止同一用户给同一笔记重复发卡。`ondelete="CASCADE"` 是数据库层的清理规则，只有实际的 MySQL 外键建立成功才有效。时间先用当前项目已有的 MySQL DATETIME 约定，跨时区策略在本篇验证里明确。

**工程位置与触发时刻：** 导入类时 SQLAlchemy 只登记结构；应用启动执行 create_all 才会给缺失表发 CREATE TABLE。创建新 Note 对象不会自动创建这个回顾行，后面还需要修改服务层。

**完成这一小步的判断：** 文件可编译；表结构包含 note_id 外键、user_id、review_count、next_review_at 与唯一约束。

**如果这里失败：** 如果导入时报找不到 Base 或 Note，核对目录层级以及 init_db 是否在建表前导入 Note 与 ReviewRecord。

### 步骤 2：【新增文件】 `backend/app/services/review_schedule.py`

**文件职责：** 集中保存初始回顾时间与后续可复用的间隔规则

**编辑文件的完整地址：**

```text
./backend/app/services/review_schedule.py
```

**完整文件内容：**

```python
"""回顾间隔规则；数据库读写留在服务层。"""
from datetime import UTC, datetime, timedelta

INTERVAL_DAYS = (1, 2, 4, 7, 15, 30)


def utc_naive_now() -> datetime:
    """MySQL DATETIME 本阶段统一存 UTC 时刻，不带时区标记。"""
    return datetime.now(UTC).replace(tzinfo=None)


def interval_for_completed_count(completed_count: int) -> int:
    if completed_count < 0:
        raise ValueError("回顾次数不能为负")
    return INTERVAL_DAYS[min(completed_count, len(INTERVAL_DAYS) - 1)]


def first_due_at(now: datetime) -> datetime:
    return now + timedelta(days=INTERVAL_DAYS[0])
```

**整体解释：** 间隔函数像一张公开的值班表：第一次提醒隔 1 天，后续章节根据已完成次数选择 2、4、7、15、30 天。把它放在独立的纯函数文件，路由不必自己算日期，测试也可以不启动数据库就检查规则。`utc_naive_now()` 不是说 UTC 可以随便去掉；它是为了和本阶段 MySQL DATETIME 无时区字段一致，所有写入和比较都必须使用同一个约定。若把本地北京时间与 UTC 混用，今日提醒会差 8 小时。

**工程位置与触发时刻：** 新建笔记时服务调用 first_due_at；第 29 篇标记已回顾时复用 interval_for_completed_count。单独导入此文件不会执行数据库写入。

**完成这一小步的判断：** 纯函数在当前 Python 环境可导入，0 次完成返回 1 天，6 次以后仍返回 30 天。

**如果这里失败：** 日期不符合预期时先打印带时区与去时区的值核对，不能在不同函数各自使用 datetime.now() 的不同约定。

### 步骤 3：【修改】 `backend/app/db/db_config.py`

**文件职责：** 把回顾模型加入建表清单

**编辑文件的完整地址：**

```text
./backend/app/db/db_config.py
```

**修改定位与前后对照：** 搜索代码块中的原函数或配置项，按 `-` 删除旧行、按 `+` 增加新行。只展示本篇变更。

```diff
@@ def init_db() -> None:
     from app.models.knowledge_document import KnowledgeDocument, KnowledgeChunk  # noqa: F401
+    from app.models.review_record import ReviewRecord  # noqa: F401

     async with async_engine.begin() as connection:
```

**整体解释：** SQLAlchemy 的 Base.metadata 像待检查的建表清单。创建类文件只相当于写好一张新表的设计图；在 init_db 中导入后，应用启动时 create_all 才知道要把这张设计图也拿去检查。它会建立缺失表，不会修改已经存在的 notes 列，也不负责数据迁移。

**工程位置与触发时刻：** lifespan 在应用开始接收请求前调用 init_db；模型 import 发生在 create_all 之前。

**完成这一小步的判断：** 重启后 MySQL 出现 review_records，原 notes 表仍存在。

**如果这里失败：** 如果表没有出现，先看 startup 是否异常，再检查模型是否被导入，而不是反复在 MySQL 手工建一张不受模型管理的表。

### 步骤 4：【修改】 `backend/app/services/note_service.py`

**文件职责：** 让新笔记和初始回顾记录在同一事务提交

**编辑文件的完整地址：**

```text
./backend/app/services/note_service.py
```

**修改定位与前后对照：** 搜索代码块中的原函数或配置项，按 `-` 删除旧行、按 `+` 增加新行。只展示本篇变更。

```diff
@@
 from app.models.note import Note
+from app.models.review_record import ReviewRecord
 from app.schemas.models import NoteCreate, NoteUpdate
+from app.services.review_schedule import first_due_at, utc_naive_now
@@ async def create_note(
         )
         db.add(note)
+        # 【新增】先写入尚未提交的父笔记，让回顾记录的外键有目标。
+        await db.flush()
+        now = utc_naive_now()
+        db.add(ReviewRecord(
+            id=str(uuid4()), note_id=note.id, user_id=user_id,
+            next_review_at=first_due_at(now), interval_days=1,
+            review_count=0,
+        ))
         await db.commit()
```

**整体解释：** 一次创建请求像同时登记一本书和它的复习卡。路由已经从令牌拿到 user_id，服务把同一个 user_id 放进 Note 和 ReviewRecord，客户端没有机会替别人建立记录。`flush()` 让数据库先看到父笔记，但事务尚未提交；接着插入回顾行，再一次 `commit()`。若外键、唯一键或连接失败，整个事务回滚，两张表不会出现一个成功一个缺失的结果。最后原有 refresh 仍读取笔记返回给前端，响应结构不被回顾字段污染。

**工程位置与触发时刻：** 只有 POST /note/create 调用 create_note 时才写回顾记录；旧笔记、更新笔记和读取列表不会触发这段写入。

**完成这一小步的判断：** 新建一篇临时笔记后，MySQL notes 和 review_records 各增加一条，note_id 与 user_id 对应。

**如果这里失败：** 若抛外键错误，先看 flush 位置和 notes 表真实主键；若提交后没有回顾行，检查服务是否还是旧进程。

## 4. 请求和状态如何穿过这些文件

下面只追踪本篇真正涉及的调用链，帮助把刚改的文件连起来；这段解释不需要复制进源码。

1. **入口：** POST /note/create 由 note_router 接受，NoteCreate 先校验标题，鉴权依赖给出当前用户 ID。
2. **会话：** get_db 为本请求提供独立 AsyncSession；它不是全局共享的“连接变量”。
3. **父行：** NoteService 构造 Note 并 add，flush 在事务中先送到 MySQL，保证后续外键可引用。
4. **子行：** 服务以同一 user_id 和新 note.id 构造 ReviewRecord，next_review_at 由 schedule 纯函数计算。
5. **提交：** 一次 commit 让两行一起对其他事务可见；失败时会话回滚。
6. **响应：** refresh Note 后走既有 NoteResponse，前端笔记页面仍只看到笔记字段。
7. **删除：** 按用户查到 Note 再删除；数据库外键级联移除回顾行。

**事务与隔离边界：** 这个事务只跨当前复刻 MySQL 的 notes 与 review_records。它不等待模型生成、Redis 更新或前端重绘；那些系统不能被同一个 MySQL commit 自动覆盖。user_id 是数据隔离的查询条件，note_id 外键是引用完整性条件，两者缺一不可。

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

**确认 notes 主键与用户字段，避免回顾表指错列**：`./backend/app/models/note.py`。把 notes 表当作已经入馆的书，回顾记录是贴在书上的借阅卡。卡上的 note_id 必须指向真实 notes.id；只记标题会在改名时失联。先阅读现有模型，确定它已经有字符串主键和 user_id，再设计外键与查询条件。这里不改文件。

可用的定位或请求片段：

```bash
rg -n "__tablename__|id =|user_id =" backend/app/models/note.py
```

观察点：应看到 notes、id、user_id 三处定义；这一步不产生数据库新表。 若不符合，如果读到的是参考仓库路径或没有 user_id，就先检查当前目录，不能凭教程假定模型结构。

**确认初始化在请求之前执行**：`./backend/app/core/lifespan.py`。生命周期函数是开门前的检查清单。`init_db` 应在 `yield` 之前执行，保证第一个创建笔记的请求到来时 review_records 已经存在；应用退出再清理连接池。如果把建表放在普通请求里，会让第一个用户承担建表竞争和失败。这里仅读取现有文件。

可用的定位或请求片段：

```bash
rg -n "init_db|yield|async_engine.dispose" backend/app/core/lifespan.py
```

观察点：确认 init_db 在 yield 前、dispose 在关闭路径。 若不符合，如果重载后表仍缺失，看终端启动栈和数据库账户是否有 CREATE 权限；不要把建表失败当成普通 404。

**编译新增文件并确认唯一键命名**：`./backend/app/models/review_record.py`。语法检查像在入库前看登记表是否能读。它能发现漏冒号、缩进或导入路径问题，但不会证明 MySQL 外键真的存在。正因为编译和运行覆盖范围不同，后面还要查数据库约束与真实创建行为。

可用的定位或请求片段：

```bash
uv run python -m compileall -q app/models/review_record.py app/services/review_schedule.py app/services/note_service.py
```

观察点：退出码为 0 且无异常输出；源码仍在原位置。 若不符合，若语法失败，先回到本篇对应 diff 处找遗漏的 import 或缩进，不要用关闭类型检查来掩盖问题。

**核对 MySQL 实际建表与外键**：`./backend/app/db/db_config.py`。正式操作时应启动 Uvicorn，让 lifespan 调用 init_db；随后用数据库管理命令查看 `review_records` 的建表语句和约束名。这里提供的是检查点而不是让读者绕开应用启动。尤其要看 `uq_review_user_note` 和指向 notes 的外键，不能只见到表名就断言隔离规则已建立。

可用的定位或请求片段：

```bash
uv run python -c "from app.db.db_config import init_db; print(init_db.__name__)"
```

观察点：SHOW CREATE TABLE 可见唯一键与外键。 若不符合，若外键缺失，检查 MySQL 是否存在旧的同名表；create_all 不会替旧表补约束，需要在后续迁移方案中处理。

**用临时笔记走真实创建链路**：`./backend/app/services/note_service.py`。真实 HTTP 请求能把之前分开的层连起来：FastAPI 校验 JSON，鉴权依赖解析用户，路由调用 NoteService，服务再在一个会话写 Note 与 ReviewRecord。这个步骤不能用只打印模型字段替代，因为那样不会触发数据库事务。保存响应中的 data.id 供下面只读核对；不要在文档里固定某个用户或笔记 ID。

可用的定位或请求片段：

```bash
curl -sS -X POST http://127.0.0.1:8100/note/create -H "Authorization: Bearer $RAG_TOKEN" -H "Content-Type: application/json" -d '{"title":"回顾记录测试","content":"本篇临时数据"}' | python3 -m json.tool
```

观察点：HTTP 200 且正文 code=200；data.id 是新笔记 ID。 若不符合，如果得到 401，先刷新本机令牌；若 500，查 Uvicorn 日志与 MySQL 外键错误，不要直接改前端。

**用同一笔记 ID 查配对关系**：`./backend/app/models/review_record.py`。配对查询只针对刚创建的临时 note_id，不扫描或展示别人的学习记录。应看到 `review_count=0`、`interval_days=1`，且 next_review_at 约在当前 UTC 时刻的一天后。若只检查 note_id 而不看 user_id，就无法发现跨账号写错归属。查询完再以该账号删除临时笔记，随后确认回顾行被外键级联清理。

可用的定位或请求片段：

```bash
docker compose exec mysql mysql -u rag_learner --password="$(sed -n 's/^MYSQL_PASSWORD=//p' ../.env)" MindWeave -e "SELECT note_id,user_id,review_count,interval_days,next_review_at FROM review_records WHERE note_id='$NOTE_ID';"
```

观察点：仅一条匹配行；删除笔记后同样查询应为 0 行。 若不符合，查询 0 行时先确认 NOTE_ID 未丢失、库名和端口指向复刻容器，再查事务是否回滚。

### 验收 1：确认正式服务使用复刻数据库

**准备与操作：** 在 backend 确认 8100 就绪，不要误连参考项目。

```bash
curl -i http://127.0.0.1:8100/health/ready
```

**期望结果：** HTTP 200 且 status=ok。

**为什么要验这一项：** 避免把另一个项目的 notes 与 review_records 混为一谈。

**不符合时从哪里查：** 端口错误先看 lsof 与 Uvicorn 工作目录。

### 验收 2：核对新表存在

**准备与操作：** 重载后从复刻 backend 目录连接 MySQL（命令中的 ../.env 指向复刻根目录）。

```bash
docker compose exec mysql mysql -u rag_learner --password="$(sed -n 's/^MYSQL_PASSWORD=//p' ../.env)" MindWeave -e "SHOW TABLES LIKE 'review_records';"
```

**期望结果：** 应出现 review_records。

**为什么要验这一项：** create_all 只有在模型导入后才知道它。

**不符合时从哪里查：** 无表先检查 init_db import 与启动日志。

### 验收 3：核对外键与唯一键

**准备与操作：** 只读查看实际 DDL。

```bash
docker compose exec mysql mysql -u rag_learner --password="$(sed -n 's/^MYSQL_PASSWORD=//p' ../.env)" MindWeave -e "SHOW CREATE TABLE review_records\G"
```

**期望结果：** DDL 中有 notes.id 外键及 uq_review_user_note。

**为什么要验这一项：** 仅看到表名不足以证明约束正确。

**不符合时从哪里查：** 旧表可能未被 create_all 更新，需记录迁移问题。

### 验收 4：创建一篇临时笔记

**准备与操作：** 用当前用户 token 发 POST，并记录 data.id 到 NOTE_ID。

```bash
curl -sS -X POST http://127.0.0.1:8100/note/create -H "Authorization: Bearer $RAG_TOKEN" -H "Content-Type: application/json" -d '{"title":"第27篇临时笔记","content":"配对验证"}' | python3 -m json.tool
```

**期望结果：** 成功响应含新 ID，稍后可查配对记录。

**为什么要验这一项：** 只有真实 HTTP 创建会触发新增服务逻辑。

**不符合时从哪里查：** 422 查标题长度；401 查 token；500 查外键。

### 验收 5：核对创建后两表同在

**准备与操作：** 用上一步 NOTE_ID 做过滤查询。

```sql
SELECT n.id,r.note_id,r.review_count,r.interval_days FROM notes n JOIN review_records r ON r.note_id=n.id WHERE n.id="<NOTE_ID>";
```

**期望结果：** 应返回同一个 ID、计数 0、间隔 1。

**为什么要验这一项：** 证明一次事务的两个写入均成功。

**不符合时从哪里查：** 不要用未限定用户和笔记的 SELECT * 展示他人数据。

### 验收 6：验证时间约定

**准备与操作：** 在数据库中查看刚建记录的 next_review_at。

```sql
SELECT UTC_TIMESTAMP() AS now_utc,next_review_at FROM review_records WHERE note_id="<NOTE_ID>";
```

**期望结果：** next_review_at 应约晚 1 天。

**为什么要验这一项：** 统一 UTC-naive 写入与读取，避免时区混用。

**不符合时从哪里查：** 若相差 8 小时，检查是否拿了本地 datetime.now()。

### 验收 7：重复创建不同笔记

**准备与操作：** 再建一篇标题相同但 ID 不同的临时笔记。

```text
POST /note/create
```

**期望结果：** 应各有一条回顾记录；唯一键按 user_id+note_id，不按标题。

**为什么要验这一项：** 验证改名或同名笔记不会混淆回顾进度。

**不符合时从哪里查：** 先核对是否误把 filename/title 作为唯一约束。

### 验收 8：错误请求无回顾行

**准备与操作：** 提交空标题或缺少 content 的请求。

```text
POST /note/create with invalid JSON
```

**期望结果：** 应为 422，notes 和 review_records 均无新行。

**为什么要验这一项：** 请求校验失败不应该走到事务。

**不符合时从哪里查：** 若出现脏数据，检查是否绕开 NoteCreate。

### 验收 9：删除后的级联

**准备与操作：** 仅删除本篇刚建的测试笔记。

```bash
curl -X DELETE "http://127.0.0.1:8100/note/$NOTE_ID" -H "Authorization: Bearer $RAG_TOKEN"
```

**期望结果：** 后续按 note_id 查 review_records 应为 0 行。

**为什么要验这一项：** 检查数据库外键实际发挥作用。

**不符合时从哪里查：** 删除失败先查用户范围，再查实际外键 DDL。

### 验收 10：重启后数据仍在

**准备与操作：** 对未删除的第二篇临时笔记重启后端并读取。

```text
GET /note/<SECOND_NOTE_ID>
```

**期望结果：** 笔记和配对行均存在，直至明确删除。

**为什么要验这一项：** 排除“只在 Python 内存里有回顾状态”的错觉。

**不符合时从哪里查：** 若重启后丢失，查数据库指向和是否误用临时库。

## 6. 深入动手与状态核对

### 把一次创建请求拆成数据库能证明的四个时刻

先用当前练习账号新建一篇临时笔记，保存响应中的 `data.id`，不要用标题当主键。标题可以重复，ID 不应重复。此时 HTTP 200 只说明路由和服务没有向客户端报告失败；它不能单独证明回顾表有行。打开专用测试库，按这个 ID 对 `notes` 与 `review_records` 做 JOIN。两行的 `user_id` 必须相同，并且等于令牌对应的用户；`note_id` 必须等于新笔记 `id`。再看 `review_count=0`、`interval_days=1`、`next_review_at` 比当前 UTC 晚约一天。这样核对的是同一次提交的完整状态，而不是“看见两张表”这种较弱的证据。

理解 `flush` 时，先把“已送给数据库执行”和“对其他请求可见”分开。服务把 Note 加进 session，`await db.flush()` 会发出 INSERT；同一个事务里的后续 INSERT 可以引用它的主键，但此时还没 `commit`。若回顾行违反外键、唯一键或连接断开，异常使事务回滚，刚才 flush 的 Note 也不应留在数据库。只有最后那次 commit 成功，另一个数据库连接才应同时看见两行。不要为了省一行代码在 Note 之后先 commit：那会打开“笔记成功、复习卡失败”的半成品窗口。

删除时反向证明约束。先用本人令牌删除刚建的临时笔记，再用原 ID 查回顾表；结果应是零行。这个结果依赖 MySQL 中真实存在 `ON DELETE CASCADE`，而不是 Python 模型文件里写了一个参数就必然生效。若库里先前已有同名旧表，`create_all` 会跳过它，可能没有外键。此时停下来记录实际 `SHOW CREATE TABLE`，按迁移方案修结构，不能通过在路由里额外执行一次宽泛 DELETE 来掩盖。只对本篇临时数据操作，尤其不要删已有学习记录。

### 迁移、时钟与故障的实际含义

如果你在第 26 篇之前已创建几十篇笔记，本篇新增模型不会为这些历史笔记补回顾行。`create_all` 处理的是表结构，不读取 notes 再逐条插入业务数据。要回填，另写有范围的脚本：按当前用户/笔记 ID 找到缺失记录、为每条生成稳定初始时间、重复运行不产生第二行，并在数据库唯一键下处理两个回填进程的竞争。没有这一步，今日列表只显示新建且到期的笔记是符合当前实现边界的结果。

当前把 UTC 时刻存进 MySQL `DATETIME`，字段本身不会替你记“这是 UTC”。写入、到期比较、临时 SQL 调整都必须采用相同坐标。用本机北京时区 `datetime.now()` 写入，却用 UTC 查询，会出现看似随机的八小时偏差。要核对偏差，比较 `UTC_TIMESTAMP()` 和刚创建记录的 `next_review_at`；不要直接拿 MySQL `NOW()` 与 UTC 字段相减，因为数据库服务器时区可能不同。将来如果“今天”是用户本地日历日，还要记录用户时区并重新定义到期边界，本篇没有实现这个产品规则。

复刻目录中可能已经有你手动写的 `review_record.py` 和 `review_schedule.py`。若文件存在，以教程完整内容逐项对照字段与函数，保留你自己的注释；尤其确认 `INTERVAL_DAYS`、`ondelete` 和唯一键。不要运行会覆盖现有文件的生成脚本，也不要因为文件存在就跳过 `init_db` 导入和 `NoteService.create_note` 的事务改动。一个模型类文件存在，不代表它已被 Base 注册、数据库已建表，更不代表创建请求会自动生成回顾行。

### 操作中最容易弄反的五个判断

一，`db.add(note)` 只把 Python 对象放进会话的待办队列，不意味着 MySQL 已持久化。`flush` 把 INSERT 送到数据库，但仍在本事务内。`commit` 才让成功状态成为其他请求可读的持久事实。验证时要用另一个请求或数据库连接读，不能只在创建函数内部打印对象；对象上已经有 ID，不等于表里已经有行。

二，`user_id` 是服务从 JWT 取得的身份，不能从 NoteCreate 里收。若请求体夹带另一个 `user_id`，Pydantic 可能忽略额外字段；服务仍应只用已验证身份创建 Note 与 ReviewRecord。数据库外键只约束 note_id 存在，不会自动判断回顾行的 user_id 是否与笔记归属一致，因此服务赋值和后续双 user_id 查询同样重要。

三，唯一键 `uq_review_user_note` 不是“防止标题重复”。用户可以创建两篇相同标题的笔记，各有不同 ID 和进度。它防止针对同一用户、同一 note_id 插入第二张回顾卡。单独在应用层先 SELECT 再 INSERT，两个并发请求仍可能都读到“没有记录”；真正兜底的是数据库唯一约束。若以后做回填，应该把该冲突当作“已补过”处理，而不是删除重建已有进度。

四，`ondelete="CASCADE"` 是数据库定义，只有建表时真实外键存在才起效。修改 Python 模型后重启，`create_all` 不会帮已经存在的表追加级联规则。删除临时笔记后留有回顾行，先看 MySQL 实际 DDL，再讨论 Alembic 或手写受控迁移；不要直接给全库跑清理 SQL，因为可能误删用户真实进度。

五，回顾调度与创建事务同在 MySQL 内，但模型生成不在这个事务里。将来给笔记自动打标签或出题时，不该把几十秒的 DeepSeek 网络调用放在持有数据库事务的期间。本篇先同步建立最小回顾行，是因为这件事只需要本地时间计算和一条 INSERT，失败时值得让创建请求整体失败。AI 失败是否影响笔记创建是另一个产品决策，后续章节按各自接口处理。

### 一份能自己复核的事务记录

在开始前写下当前复刻库的 `notes` 与 `review_records` 行数，只在当前练习账号范围内计数。发一次正常创建请求，保存返回的 UUID，再分别从两张表按同一个 ID 查记录；计数都应该各加一。随后向创建接口发一个无效标题，得到 422 后两张表都不应该增加。注意这个负向请求是在 Pydantic 边界被挡住的，尚未验证“第二条 INSERT 失败导致第一条回滚”；若要证明后者，需在专用测试事务中故意触发唯一键或外键错误，并在事务退出后用另一个连接核对两张表。这种故障注入不要对真实笔记执行。

还可以观察 SQLAlchemy 的时序：打开开发环境 SQL 日志或临时在服务关键位置记录非敏感事件，应该依次看到 Note INSERT、ReviewRecord INSERT、COMMIT，而不是第一个 INSERT 后立刻 COMMIT。日志中不要记录笔记全文、JWT、数据库密码。若业务异常发生在 COMMIT 前，接下来应出现 ROLLBACK；若数据库驱动在连接断开时无法完成回滚，会话关闭仍要释放池连接，客户端收到错误。`get_db` 负责请求结束时清理会话，`NoteService` 负责什么时候提交，两者职责不同。

最后把这篇临时笔记删除，再按原 UUID 查回顾表应无行。不要先把 `review_records` 里的行手工删掉再验证级联，那样会把数据库约束是否生效这个问题遮住。若你准备继续第 28 篇，保留另一篇只用于测试的笔记并记录其 ID 和用户；把它的 `next_review_at` 临时调到过去，下一篇的今日列表才有可见数据。操作后把临时数据清理掉，避免练习结果混进日常回顾。

**离开本篇前保留的最小证据：** 一次创建请求的 HTTP 状态与新 UUID；同一 UUID 在 notes 和 review_records 中的配对行；两行同一个 user_id；初始计数与到期时间；删除该临时 Note 后回顾行消失。若这些证据缺一，先不要进入今日列表，否则第 28 篇的空结果无法判断究竟是时间未到、事务没有写卡，还是 JOIN 条件错误。

## 7. 工程面试思考

回答时要指向本篇具体文件、数据库约束或接口结果，区分当前已实现、验证时才可能观察到的结果与未来扩展。这里讨论设计判断，不背诵通用定义。

**面试官：为什么不把 review_count 和 next_review_at 直接加进 notes 表？**

回顾进度与笔记正文属于不同生命周期。独立 review_records 表使回顾查询可以按 next_review_at 建索引，后续还能扩展多种回顾策略；代价是创建时多写一行、读取时要 JOIN。当前项目参考实现本来就有 ReviewRecord，因此复刻保持此职责。只有真的需要多用户共享同一笔记时，唯一键和归属设计才需要重新审视。

**面试官：创建笔记成功却没有回顾记录会怎样防？**

本篇在同一 AsyncSession 中先 flush 父 Note，再 add 子 ReviewRecord，最后只 commit 一次。flush 不是提交，异常时 rollback 能撤销两行。数据库外键和唯一键是最后一道保护。真正验收要在 MySQL 看两行的对应关系，不能只看 POST 返回 200。

**面试官：两个请求同时创建回顾记录怎么办？**

同一 note_id 的重复记录会被 uq_review_user_note 唯一键挡住；如果是两个不同 note_id，允许各自一条。应用层可以先查减少友好错误，但“先查后写”不能消除并发窗口，因此仍需要数据库约束。具体重复插入如何映射业务响应可在后续服务层处理。

**面试官：为什么时间统一用 UTC？**

MySQL DATETIME 本身不附带时区。统一把 UTC 时刻以 naive datetime 存储，可在当前系统里稳定比较到期时间；但所有读写必须一致。若以后有用户时区和“当地零点”的需求，应在 API 层存用户时区、在数据库存 UTC，并明确“今天”的业务定义。

## 8. 常见故障的定位顺序

- **启动失败：** 先看数据库连接与 init_db 模型导入；不要为了让 /ready 变绿删除已有表。
- **外键错误：** 确认 Note 在同一事务内先 flush，review_records 的 note_id 与 Note.id 一致。
- **历史笔记无回顾行：** 本章只为新建笔记写卡；对既有数据的回填应另做有范围、有幂等性的迁移。
- **时间差异：** 查看 MySQL UTC_TIMESTAMP 与应用 utc_naive_now 的约定，避免本地时间混写。
- **删除仍有记录：** 检查 SHOW CREATE TABLE 的 ON DELETE CASCADE，不能只信模型源码。

## 9. 本篇边界和下一篇

本篇交付的是回顾数据的可靠起点，还没有“今日列表”页面接口。下一篇用 review_records 与 notes 的 JOIN 查询当前用户到期笔记，给复制来的 DailyReview 页面真实数据。

本篇没有修改前端文件。新代码完成并经过你本机的验证后，才把它记为你亲手完成；仅阅读教程、助手先前的隔离检查或接口文档出现新路径，都不能代替真实执行。
