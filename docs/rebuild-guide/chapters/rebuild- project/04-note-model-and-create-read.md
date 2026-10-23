# 第 04 篇：建立笔记表，真正完成创建、列表与详情读取

> 日期：2026-10-20。新版连续教程；面向有 Python、HTTP、JSON 与异步基础的读者。 
> 前置：完成[上一篇](03-mysql-and-async-session.md)，从该篇最终文件继续。 
> 本篇成果：POST /note/create 实际写入 MySQL；GET /note/list 和 /note/{note_id} 读取已保存的数据，重启后仍可读。 
> 交付状态：本篇代码已写入正式复刻目录，并用真实 MySQL 完成接口与重启后读取验证。

## 1. 本篇目标与操作起点

复刻根目录固定为：

```text
.
```

文中所有 backend/、app/ 等位置都以这里为准，不在上一级参考项目中写代码。本篇已在正式复刻项目完成；后续篇章仍按顺序操作，不直接跳到最后一篇复制入口文件。

前置不是“知道上一章”，而是第 03 篇文件已经完成、MySQL 正常运行、/health/ready 为 200。本篇第一次增加数据库表，继续沿用同一数据库和会话工厂。

基础语法直接使用。本篇围绕正在创建的文件说明职责、数据与调用关系，重点解释新机制和为什么这样组织。
## 2. 目录与责任划分

| 标记 | 路径 | 本篇负责什么 |
|---|---|---|
| 【新增文件夹】 | app/models、app/services、app/utils | 分别放表映射、业务处理和依赖工具 |
| 【新增文件】 | models/base.py、models/note.py 及包标识 | 建立统一元数据和 notes 表映射 |
| 【修改】 | schemas/models.py | 加入响应模型与列表外壳 |
| 【修改】 | db/db_config.py、core/lifespan.py | 注册模型并在启动阶段建表 |
| 【新增文件】 | utils/auth_utils.py | 临时演示用户依赖，后续换成 JWT |
| 【新增文件】 | services/note_service.py | 创建与查询笔记，显式提交写入 |
| 【新增文件】 | router/note_router.py | 接收 HTTP、校验输入、注入依赖和输出响应 |
| 【修改】 | main.py | 接入笔记路由组 |

先把“谁负责什么”固定下来：schemas 是输入输出规格，models 是数据库映射，service 执行业务，router 组织 HTTP 调用。路由函数不直接堆所有 SQL，模型类也不自己判断用户当前是否登录。

本阶段尚未实现用户系统，演示用户固定为 learning-user。user_id 会真实写入并用于所有查询过滤，但所有本地请求暂时属于同一个演示用户；这不是 JWT 鉴权，也不能作为已完成真实用户隔离的交付。本地服务继续只监听 127.0.0.1。

## 3. 按顺序建立文件

**执行位置：复刻 backend。**
```bash
cd "./backend"
mkdir -p app/models app/services app/utils
```
### 步骤 1：【新增文件】 `backend/app/models/__init__.py`

**编辑文件的完整地址：**

```text
./backend/app/models/__init__.py
```

**新建说明：** 先确认父目录已按本篇命令创建，再新建同名文件；整个文件都是本步新增内容。

**完整文件内容：**

<!-- file: backend/app/models/__init__.py -->
```python
"""数据库表映射与统一元数据。"""
```

**作用：** 每个表映射都使用同一份 Base，后面统一建表时才能找到。包标识文件本身不执行数据库操作。

### 步骤 2：【新增文件】 `backend/app/services/__init__.py`

**编辑文件的完整地址：**

```text
./backend/app/services/__init__.py
```

**新建说明：** 先确认父目录已按本篇命令创建，再新建同名文件；整个文件都是本步新增内容。

**完整文件内容：**

<!-- file: backend/app/services/__init__.py -->
```python
"""笔记等业务处理逻辑。"""
```

**作用：** 服务层承接路由交来的输入与会话，明确组织查询、写入和提交。包标识文件本身不执行数据库操作。

### 步骤 3：【新增文件】 `backend/app/utils/__init__.py`

**编辑文件的完整地址：**

```text
./backend/app/utils/__init__.py
```

**新建说明：** 先确认父目录已按本篇命令创建，再新建同名文件；整个文件都是本步新增内容。

**完整文件内容：**

<!-- file: backend/app/utils/__init__.py -->
```python
"""可复用的依赖与小工具。"""
```

**作用：** 当前用于演示用户依赖，后续会接真正的身份解析。包标识文件本身不执行数据库操作。

### 步骤 4：【新增文件】 `backend/app/models/base.py`

**编辑文件的完整地址：**

```text
./backend/app/models/base.py
```

**新建说明：** 先确认父目录已按本篇命令创建，再新建同名文件；整个文件都是本步新增内容。

**完整文件内容：**

<!-- file: backend/app/models/base.py -->
```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """全部数据库模型共享同一份 metadata。"""
```

**文件职责：** 给所有 ORM 模型提供共同的基类和表元数据集合。

可以把 metadata 看作准备交给施工方的图纸册：每个模型定义把自己登记到这份册子里，create_all 才知道要检查哪些表。若每个文件都临时定义一份 Base，就像每个工种各拿一本互不相通的图纸，统一建表看不到别人的内容。

参考项目将 Base 放在 chat_history 模型附近；复刻目前还没做聊天，先独立放到 models/base.py，后续模型继续导入同一个 Base，不额外造第二份。

### 步骤 5：【新增文件】 `backend/app/models/note.py`

**编辑文件的完整地址：**

```text
./backend/app/models/note.py
```

**新建说明：** 先确认父目录已按本篇命令创建，再新建同名文件；整个文件都是本步新增内容。

**完整文件内容：**

<!-- file: backend/app/models/note.py -->
```python
from sqlalchemy import JSON, Boolean, Column, DateTime, String, Text, func

from app.models.base import Base


class Note(Base):
    __tablename__ = "notes"

    # 【新增】字段与参考 Note 的核心结构对齐。
    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), index=True, nullable=False)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    tags = Column(JSON, nullable=True)
    category = Column(String(50), nullable=True)
    is_pinned = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

**文件作用：** 把 Python 的 Note 对象与 MySQL 的 notes 表关联，字段类型和主要容量对照参考模型。

`__tablename__` 决定表名。id 使用 UUID 字符串，user_id 为后续用户筛选提供索引；索引帮助定位但不等于权限控制，真正的查询仍要写 user_id 条件。

JSON 列保存标签列表，Text 保存 Markdown 正文。这里的 JSON 是数据库列类型，与 HTTP 请求中的 JSON 使用场景不同：前者决定存储方式，后者决定数据交换格式。

数据库默认值和 Python 默认值的触发点不同：is_pinned 的 default=False 由 SQLAlchemy 在插入时提供，created_at 的 server_default 交给数据库生成。刚构造 Note 时不能假设数据库时间已经填好，这也是后面 refresh 的原因。

updated_at 的 onupdate 让 ORM 产生更新时携带更新时间表达式，不代表任何外部 SQL 修改都会被数据库触发器捕获。本篇 MySQL 服务按 UTC 初始化，DateTime 列不存时区偏移；前端展示时再按明确约定转换，不把无偏移字符串误当本地时间。

声明模型本身不会立刻建表，下一步必须导入模型并执行统一 metadata 的 create_all。

### 步骤 6：【修改】`backend/app/schemas/models.py`

**编辑文件的完整地址：**

```text
./backend/app/schemas/models.py
```

**修改定位与前后对照：** 根据下列函数名、配置项或导入位置定位；diff 仅供阅读，正负号不要复制进源码。对照以完成上一篇后的版本为准，请按 diff 修改已有文件。

```diff
--- backend/app/schemas/models.py（修改前）
+++ backend/app/schemas/models.py（修改后）
@@ -1,4 +1,6 @@
-from pydantic import BaseModel, Field, field_validator
+from datetime import datetime
+
+from pydantic import BaseModel, ConfigDict, Field, field_validator
 
 
 class NoteCreate(BaseModel):
@@ -12,3 +14,21 @@
     @classmethod
     def normalize_title(cls, value):
         return value.strip() if isinstance(value, str) else value
+class NoteResponse(BaseModel):
+    # 【新增 C01】允许从 ORM 对象属性读取响应字段。
+    model_config = ConfigDict(from_attributes=True)
+
+    id: str
+    user_id: str
+    title: str
+    content: str
+    tags: list[str] | None = None
+    category: str | None = None
+    is_pinned: bool = False
+    created_at: datetime | None = None
+    updated_at: datetime | None = None
+
+
+class NoteListResponse(BaseModel):
+    notes: list[NoteResponse]
+    total_count: int
```

**整体解释：** 数据库取出 Note 对象后，响应模型像一张出库清单，只将允许公开的笔记字段整理给客户端。它不会创建表或保存记录，而是在服务查到数据之后，将 ORM 属性变成稳定的接口结果。在既有 NoteCreate 后加入 NoteResponse 和 NoteListResponse，原输入规则保持不变。Note 是数据库对象，NoteResponse 是允许交给客户端的输出规格，两者不要直接混为一谈。from_attributes=True 让 model_validate(note) 从 ORM 属性提取 id、title 等字段，而不是要求 note 已经是字典。响应模型中时间字段采用 datetime，公共 success_response 内的 jsonable_encoder 会把它们序列化为字符串，所以客户端依然收到 JSON 字符串。这里没有把 ORM 的内部状态 _sa_instance_state 一起发给前端。列表外壳沿用原项目 notes、total_count 字段，后面分页时 total_count 表示筛选后的总量，不是当前页长度。本篇暂时一次返回当前演示用户的全部笔记，第 06 篇再加入分页与筛选。

### 步骤 7：【修改】`backend/app/db/db_config.py`

**编辑文件的完整地址：**

```text
./backend/app/db/db_config.py
```

**修改定位与前后对照：** 根据下列函数名、配置项或导入位置定位；diff 仅供阅读，正负号不要复制进源码。对照以完成上一篇后的版本为准，请按 diff 修改已有文件。

```diff
--- backend/app/db/db_config.py（修改前）
+++ backend/app/db/db_config.py（修改后）
@@ -4,6 +4,7 @@
 from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
 
 from app.core.settings import settings
+from app.models.base import Base
 
 # 【新增】用结构化 URL 处理密码中的 @、: 等字符。
 database_url = URL.create(
@@ -48,3 +49,9 @@
         return True
     except Exception:
         return False
+async def init_db() -> None:
+    # 【新增 C01】导入模型完成注册后，统一检查并创建缺失表。
+    from app.models.note import Note  # noqa: F401
+
+    async with async_engine.begin() as connection:
+        await connection.run_sync(Base.metadata.create_all)
```

**整体解释：** Base.metadata 像待建表登记簿：导入 Note 会把 notes 表写进登记簿，init_db 让 create_all 对照数据库补建缺失的表。这里铺好的是空货架，具体笔记仍要等创建服务提交事务才会出现。顶部导入 Base，文件末尾增加 init_db。原引擎、get_db、连接检查原样保留。`from app.models.note import Note` 的作用不是读取一条笔记，而是让 Note 类定义执行，将 notes 表登记到同一份 metadata。必须先注册，再 create_all。引擎 begin 上下文提供连接与事务边界，run_sync 是 SQLAlchemy 提供的同步元数据操作桥接方式，用于在异步连接上运行 create_all。它不代表任意阻塞函数都可以随便塞进去变成高效异步。create_all 会创建缺失的表，不会自动迁移已有列、删除旧表或清空数据。后续修改字段结构时需要迁移方案，不能把这个函数当万能数据库升级器。本篇没有 drop_all。

### 步骤 8：【修改】`backend/app/core/lifespan.py`

**编辑文件的完整地址：**

```text
./backend/app/core/lifespan.py
```

**修改定位与前后对照：** 根据下列函数名、配置项或导入位置定位；diff 仅供阅读，正负号不要复制进源码。对照以完成上一篇后的版本为准，请按 diff 修改已有文件。

```diff
--- backend/app/core/lifespan.py（修改前）
+++ backend/app/core/lifespan.py（修改后）
@@ -3,16 +3,16 @@
 from fastapi import FastAPI
 from sqlalchemy import text
 
-from app.db.db_config import async_engine
+from app.db.db_config import async_engine, init_db
 
 
 @asynccontextmanager
 async def lifespan(app: FastAPI):
     try:
-        # 【新增】启动时先验证本项目账户可以连接目标数据库。
         async with async_engine.connect() as connection:
             await connection.execute(text("SELECT 1"))
+        # 【新增 C01】开始接收请求前，保证本阶段的表已经存在。
+        await init_db()
         yield
     finally:
-        # 【新增】启动失败或应用正常关闭时，都释放连接池资源。
         await async_engine.dispose()
```

**整体解释：** 建表函数写好后，lifespan 负责在开门前调用它：数据库连接检查通过，紧接着准备 notes 表，最后才开始接请求。这样第一位创建笔记的用户不会撞上“表不存在”；启动失败也会走关闭清理。在连接检查成功后、yield 开门接待前调用 init_db。以后即使服务第一次启动，notes 表也会先准备好。若建表权限不足，启动失败并通过 finally 清理连接资源；不能让第一位创建笔记的调用者才碰到“表不存在”。但应用正常启动不代表所有未来 SQL 都不会失败，实际写入仍需明确提交和错误传播。

### 步骤 9：【新增文件】 `backend/app/utils/auth_utils.py`

**编辑文件的完整地址：**

```text
./backend/app/utils/auth_utils.py
```

**新建说明：** 先确认父目录已按本篇命令创建，再新建同名文件；整个文件都是本步新增内容。

**完整文件内容：**

<!-- file: backend/app/utils/auth_utils.py -->
```python
DEMO_USER_ID = "learning-user"


async def get_current_user_id() -> str:
    # 【新增】仅限当前本机学习阶段；后续换成 JWT 验证后取得真实用户编号。
    return DEMO_USER_ID
```

**文件职责与临时边界：** 给路由一个统一的“当前用户编号”来源。所有路由先调用同一个依赖，以后替换实现时不用逐个接口重写身份参数。

当前函数不检查 token、不读取请求头，不接受客户端提交的 user_id。固定 learning-user 只是阶段性桩实现；不能靠它提供多账户登录。第 02 篇 NoteCreate 也没有 user_id 字段，所以客户端无法通过输入模型随意指定笔记归属。

虽然身份来源临时简化，服务层依然从现在开始把 user_id 写入和带入每条查询。真正 JWT 接入时会把这个桩函数替换掉，并增加两个真实用户的隔离验证。

### 步骤 10：【新增文件】 `backend/app/services/note_service.py`

**编辑文件的完整地址：**

```text
./backend/app/services/note_service.py
```

**新建说明：** 先确认父目录已按本篇命令创建，再新建同名文件；整个文件都是本步新增内容。

**完整文件内容：**

<!-- file: backend/app/services/note_service.py -->
```python
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.note import Note
from app.schemas.models import NoteCreate


class NoteService:
    async def create_note(
        self, db: AsyncSession, user_id: str, payload: NoteCreate
    ) -> Note:
        # 【新增】字段来源明确，归属取服务端依赖，不信任客户端 user_id。
        note = Note(
            id=str(uuid4()),
            user_id=user_id,
            title=payload.title,
            content=payload.content,
            tags=payload.tags,
            category=payload.category,
        )
        db.add(note)
        await db.commit()
        await db.refresh(note)
        return note

    async def get_note(
        self, db: AsyncSession, note_id: str, user_id: str
    ) -> Note | None:
        statement = select(Note).where(Note.id == note_id, Note.user_id == user_id)
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def list_notes(self, db: AsyncSession, user_id: str) -> list[Note]:
        statement = (
            select(Note)
            .where(Note.user_id == user_id)
            .order_by(Note.updated_at.desc(), Note.id.desc())
        )
        result = await db.execute(statement)
        return list(result.scalars().all())


# 【新增】服务对象不保存会话或用户状态，可以被各请求复用。
note_service = NoteService()
```

**文件作用：** 收到“当前会话、当前用户、校验后的输入”，执行创建和查询，不直接处理 Request 或请求头。

**创建链路的四个动作：** 构造 Note 只是内存对象；add 是把它放进会话待处理范围；commit 才提交数据库事务；refresh 再取回数据库生成的字段。这像先整理登记材料、放进待办篮、正式登记入册，再拿回带编号时间的回执。篮子里放好了不等于已经入册。

UUID 在应用里生成，生成后不保证一定保存成功；commit 失败时函数不会走到 return，get_db 的异常分支会 rollback 并继续向外抛。若 refresh 在提交后失败，数据库中的写入可能已经存在，不能把“响应失败”一概理解成“数据库完全没变”；实际系统后续还要设计重试与幂等策略。

get_note 同时限定 id 和 user_id，一次查询表达“找这位用户的这条笔记”。如果只按 id 查，未来知道他人 UUID 的用户可能越界读取。这里为后续身份体系预留的是业务约束，不是依靠 UUID 难猜来当权限。

scalar_one_or_none 返回一个对象或 None；list_notes 的 scalars().all() 取得模型对象列表，避免把查询 Row 包装对象当业务数据。排序增加 id 作为同时间戳的稳定次序，后续分页会继续用到。

note_service 本身不缓存数据库 Session。每个请求传进来的 db 不同，所以复用这个无状态服务实例不等于让多个请求共享一份事务。

### 步骤 11：【新增文件】 `backend/app/router/note_router.py`

**编辑文件的完整地址：**

```text
./backend/app/router/note_router.py
```

**新建说明：** 先确认父目录已按本篇命令创建，再新建同名文件；整个文件都是本步新增内容。

**完整文件内容：**

<!-- file: backend/app/router/note_router.py -->
```python
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.success_response import success_response
from app.db.db_config import get_db
from app.schemas.models import NoteCreate, NoteListResponse, NoteResponse
from app.services.note_service import note_service
from app.utils.auth_utils import get_current_user_id

note_router = APIRouter(prefix="/note", tags=["note"])


@note_router.post("/create")
async def create_note(
    payload: NoteCreate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    note = await note_service.create_note(db, user_id, payload)
    return success_response(message="笔记创建成功", data=NoteResponse.model_validate(note))


@note_router.get("/list")
async def list_notes(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    notes = await note_service.list_notes(db, user_id)
    data = NoteListResponse(
        notes=[NoteResponse.model_validate(note) for note in notes],
        total_count=len(notes),
    )
    return success_response(data=data)


@note_router.get("/{note_id}")
async def get_note(
    note_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    note = await note_service.get_note(db, note_id, user_id)
    if note is None:
        return success_response(message="笔记不存在")
    return success_response(data=NoteResponse.model_validate(note))
```

**文件职责：** 把 HTTP 与业务连接起来：声明参数、拿依赖、调用服务、把结果转换为响应。

Depends(get_current_user_id) 让框架为当前请求取得用户编号，Depends(get_db) 让框架进入异步生成器取到 Session，并在请求处理结束后做清理。这里传函数对象，没有括号；调用时机交给 FastAPI，而不是在导入模块时就创建一次会话。

payload: NoteCreate 将第 02 篇定义的模型用到真实 HTTP 请求上。非法标题或缺少正文时，框架在执行 create_note 处理体之前就拒绝，进入统一 422 处理器；服务和 commit 不应该被调用。

`/list` 是固定路径，放在 `/{note_id}` 之前。否则某些读取请求可能先把 list 当成笔记编号，得到“笔记不存在”；注册规则有顺序，不能只看函数名字猜匹配行为。

详情不存在沿用参考接口的兼容形式：HTTP 200、正文 code=200、message=笔记不存在、data=null。它与未知路由的 HTTP 404 是不同约定，前端需要检查 data 和消息；本阶段不擅自改成另一种 API 契约。

本篇 list 暂未分页，会返回此演示用户全部记录；第 06 篇将调整该函数和相应服务，输出字段保持 notes、total_count。

### 步骤 12：【修改】`backend/main.py`

**编辑文件的完整地址：**

```text
./backend/main.py
```

**修改定位与前后对照：** 根据下列函数名、配置项或导入位置定位；diff 仅供阅读，正负号不要复制进源码。对照以完成上一篇后的版本为准，请按 diff 修改已有文件。

```diff
--- backend/main.py（修改前）
+++ backend/main.py（修改后）
@@ -4,11 +4,14 @@
 from app.core.lifespan import lifespan
 from app.core.settings import settings
 from app.router.health import health_router
+from app.router.note_router import note_router
 
 # 【修改 C01】应用启动检查和关闭清理由 lifespan 管理。
 app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
 
 app.include_router(health_router)
+# 【新增 C01】把笔记接口组注册到同一个应用。
+app.include_router(note_router)
 register_exception_handlers(app)
```

**整体解释：** 笔记路由文件已经写好窗口规则，include_router 才把窗口挂进 FastAPI 大厅。应用启动时登记 /note 下的路径，后续请求才会分发到创建和读取函数；登记本身不会自动生成笔记。顶部导入 note_router，在原健康路由注册后增加 include_router。现有健康接口、生命周期和异常处理不删除。你已经问过 include_router，本篇直接把同一机制用于第二张路由表。它登记 /note 下的规则，不会在启动时自动创建一篇笔记；实际创建必须由请求触发。可回看[Q003](../03-knowledge-q-and-a.md#q003)。

## 4. 一篇笔记从请求到数据库的路径

以“第一篇持久化笔记”为输入：HTTP 正文 → NoteCreate 规范化与校验 → 当前用户依赖返回 learning-user → get_db 交出当前请求的会话 → 服务构造 Note → add → commit → refresh → NoteResponse 提取输出字段 → success_response 编码为 JSON。

校验是入场检查，事务提交是落库动作，输出模型是对外规格。三个环节不能互相替代。把这条路径对照到刚创建的文件，就能分清哪里是字段规则、哪里是 SQL、哪里是 HTTP 格式。

## 5. 启动、创建和读取

先确认第 03 篇 MySQL 容器已运行；完成全部文件保存后，手动启动或等待现有服务重载：
```bash
cd "./backend"
uv run uvicorn main:app --reload --host 127.0.0.1 --port 8100
```
**执行位置：终端 B，任意目录。创建真实数据：**
```bash
curl -i -X POST http://127.0.0.1:8100/note/create   -H 'Content-Type: application/json'   -d '{"title":"  第一篇持久化笔记  ","content":"重启后还应能读取。","category":"study","tags":["RAG","学习"]}'
```
预期 HTTP 200、message=笔记创建成功，data 中出现 UUID、learning-user、整理后的标题、时间和 is_pinned=false。复制返回的实际 id，用于下面的详情地址；不要把文档中的占位值直接当数据库里已存在的编号。
```bash
curl -i http://127.0.0.1:8100/note/list
curl -i http://127.0.0.1:8100/note/替换为返回的实际id
curl -i http://127.0.0.1:8100/note/not-exists
```
list 应含刚创建的记录，详情字段与创建响应一致，不存在的编号按上面约定返回 data=null。重新执行创建会新增另一条数据，不是自动更新上一条。

**非法输入验证：**
```bash
curl -i -X POST http://127.0.0.1:8100/note/create   -H 'Content-Type: application/json'   -d '{"title":"   ","content":"这条不应保存"}'
```
应返回 HTTP 422，data 中定位 body/title。再次查列表，数量不应因为这次请求增加。

**持久化验证：** 在终端 A 停止并重新启动后端，再读取刚才的实际 id，应仍存在。进一步可在复刻根目录执行 docker compose restart mysql，等待 healthy 后重新查询；这不是清空数据。

**直接核对数据库：** 进入第 03 篇的 MySQL 命令行后执行：
```sql
SHOW TABLES;
SELECT id, user_id, title, is_pinned, created_at FROM notes ORDER BY created_at DESC LIMIT 5;
```
若 API 返回成功但库里看不到记录，先确认连接的是复刻的 13306 和 MindWeave，而不是原项目数据库。数据库是最直接的落库证据，终端 print 和模型对象都不能代替。

## 6. 常见问题

| 现象 | 定位重点 | 说明 |
|---|---|---|
| notes 表不存在 | lifespan 是否 await init_db、模型是否先导入 | create_all 只看已注册模型 |
| /note/list 返回笔记不存在 | 固定路径与动态路径顺序 | list 应登记在 /{note_id} 前 |
| 时间字段为空或类型转换失败 | commit、refresh、NoteResponse 配置 | 数据库默认值要在写入后读取 |
| 变更没有进数据库 | 是否实际执行 commit | add 只进入会话，不代表已提交 |
| InvalidRequestError/会话状态混乱 | 是否全局共用了 AsyncSession | 服务无状态，会话由请求传入 |
| MissingGreenlet | 失效属性或隐式数据库读取 | 保留 expire_on_commit=False，明确 refresh |

## 7. 做完后核对与下一步

- [x] notes 表存在，创建接口返回真实 UUID。
- [x] 详情与列表的查询都含 user_id 条件。
- [x] 非法请求返回 422，未新增记录。
- [x] 重启后仍能读取记录，未使用字典冒充持久化。
- [x] 成功响应经 NoteResponse 转换，没有发送 ORM 内部字段。

本篇业务代码不新增第三方依赖；真实 MySQL 验证时补齐了第 03 篇需要固定的 PyMySQL 版本。下篇[修改、删除与置顶](05-note-update-delete-and-pin.md)会在同一 service/router 中增加操作，所有变更都有 diff 与最终文件，不另起一套并行实现。

当前仍缺少 JWT、真实用户表、限流、AI 标签和图谱任务。创建路由路径与核心返回字段对齐参考实现，后台知识处理将在对应阶段补上，当前 tags 采用请求传入值，不假称已经调用模型自动生成。

**参考源码：** [Note 表](../../../backend/app/models/note.py)、[笔记服务](../../../backend/app/services/note_service.py)、[笔记路由](../../../backend/app/router/note_router.py)。

### 本篇验证记录

**已执行流程与 HTTP 验证（2026-10-20）**：从文档依次提取完整文件，在临时 SQLite 数据库实际建表；创建、列表、详情、响应时间序列化、非法请求 422、应用停止后重启读取均通过。通过测试专用依赖覆盖，分别注入两个用户编号，验证查询中的 user_id 条件；这不是 JWT 验证，正式源码仍为演示用户。

**正式复刻目录的真实 MySQL 验证（2026-10-20）**：应用账户连接成功，`notes` 表实际创建；`POST /note/create` 返回 UUID，`GET /note/list` 与详情返回刚写入的笔记；空白标题返回 422，未增加记录；重启后端后按原 ID 仍可读取。数据库命令行已直接查到 `notes` 表及该记录。用另一用户编号调用服务时，详情为 `None`、列表为空。当前服务运行在 `127.0.0.1:8100`，数据库容器 healthy。容器重启和两个真实登录用户的隔离尚未验证；后者要等 JWT 阶段。

**前置问题与处理**：补齐第 02 篇缺失的异常处理注册文件；本地 `.env` 应用密码与运行中的容器不一致，已恢复为容器当前值且未输出密码；将 PyMySQL 固定为 1.1.3，以避开现有 SQLAlchemy 与 PyMySQL 1.2.x 的连接池 `ping()` 兼容问题。

本轮临时验证记录：`/tmp/verification-results.json`。所有验证服务均已停止；正式 8100 服务及其源码不参与本轮变更。
