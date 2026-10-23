# 第 05 篇：补齐笔记修改、删除与置顶，理解局部更新和事务

> 日期：2026-10-20。新版连续教程；面向有 Python、HTTP、JSON 与异步基础的读者。 
> 前置：完成[上一篇](04-note-model-and-create-read.md)，从该篇最终文件继续。 
> 本篇成果：PUT /note/{id} 更新字段，PUT /note/{id}/pin 切换置顶，DELETE /note/{id} 真正删除数据库记录。 
> 交付范围：本篇是操作教材，代码在独立临时目录验证；不会自动把新增代码写入你的正式复刻目录。

## 1. 本篇目标与操作起点

复刻根目录固定为：

```text
.
```

文中所有 backend/、app/ 等位置都以这里为准，不在上一级参考项目中写代码。用户当前正式项目只执行到新版第 01 篇；本篇及后续篇章需要按顺序完成，不能直接跳到最后一篇复制入口文件。

本篇只修改已有 schemas/models.py、services/note_service.py、router/note_router.py，不新建目录，不改 main.py 和依赖。第 04 篇已经注册过 note_router，往这个路由组增加规则后，重载即可被应用接入。

基础语法直接使用。本篇围绕正在创建的文件说明职责、数据与调用关系，重点解释新机制和为什么这样组织。
## 2. 本次修改清单

| 标记 | 修改位置 | 变化 |
|---|---|---|
| 【新增】 | schemas/models.py 的 NoteUpdate | 允许局部修改，区分“未传”和“传 null” |
| 【新增】 | NoteService | update_note、delete_note、toggle_pin |
| 【新增】 | note_router | PUT 更新、PUT 置顶、DELETE 删除 |
| 【查看】 | main.py | 复用已经存在的 include_router，不重复注册 |

本篇所有接口继续按当前用户过滤。前一篇的创建、列表、详情都保留，不为了新增功能丢掉旧功能。diff 标出本次新增位置；按对照修改已有文件，并保留没有列出的旧功能。

## 3. 按顺序修改三个文件

先完成输入模型，再服务，再路由。假如自动重载在保存途中报 NoteUpdate 无法导入，先确认这三个文件是否都保存完成，不要改成从别的目录导入来绕过。
### 步骤 1：【修改】`backend/app/schemas/models.py`

**编辑文件的完整地址：**

```text
./backend/app/schemas/models.py
```

**修改定位与前后对照：** 根据下列函数名、配置项或导入位置定位；diff 仅供阅读，正负号不要复制进源码。对照以完成上一篇后的版本为准，请按 diff 修改已有文件。

```diff
--- backend/app/schemas/models.py（修改前）
+++ backend/app/schemas/models.py（修改后）
@@ -1,6 +1,6 @@
 from datetime import datetime
 
-from pydantic import BaseModel, ConfigDict, Field, field_validator
+from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
 
 
 class NoteCreate(BaseModel):
@@ -32,3 +32,24 @@
 class NoteListResponse(BaseModel):
     notes: list[NoteResponse]
     total_count: int
+
+
+class NoteUpdate(BaseModel):
+    # 【新增 C01】所有字段可省略，但明确传 null 有单独约定。
+    title: str | None = Field(default=None, min_length=1, max_length=200)
+    content: str | None = None
+    category: str | None = Field(default=None, max_length=50)
+    tags: list[str] | None = None
+    is_pinned: bool | None = None
+
+    @field_validator("title", mode="before")
+    @classmethod
+    def normalize_title(cls, value):
+        return value.strip() if isinstance(value, str) else value
+
+    @model_validator(mode="after")
+    def reject_null_for_required_columns(self):
+        for name in ("title", "content", "is_pinned"):
+            if name in self.model_fields_set and getattr(self, name) is None:
+                raise ValueError(f"{name} 不能显式设为 null")
+        return self
```

**整体解释：** 更新笔记像修改一张已有表单，可以只交新标题，不必重写正文。新增模型保留“字段没交”和“明确交了空值”的差别，服务才知道该保持原值还是清空字段；标题提交时仍先做空白整理。新增 NoteUpdate；既有创建与响应模型保留。更新请求允许只传一个字段，不强迫用户把整篇笔记的所有内容再交一遍。这里最重要的不是字段可选这个语法，而是三个业务状态：没传 category 表示保持原值；传 category=null 表示清空分类；传 category="study" 表示换成新分类。它们在更新时必须区别对待。`model_fields_set` 记录调用方实际提供的字段，后面的 `model_dump(exclude_unset=True)` 只保留这些字段。不是简单地把所有 None 都扔掉：否则无法清空分类；也不能把所有默认 None 都写回数据库：否则只改标题会意外清空正文和标签。title、content、is_pinned 对应非空列，明确传 null 时在输入阶段拒绝；category、tags 可清空，允许 None。模型整体校验发生在字段转换之后，能同时观察“值是什么”和“这个字段是否真的传过”。空对象 {} 可以先构造为 NoteUpdate，但服务层会拒绝“没有任何修改字段”的业务请求。空对象的语法合法和业务上值得执行是两回事。

### 步骤 2：【修改】`backend/app/services/note_service.py`

**编辑文件的完整地址：**

```text
./backend/app/services/note_service.py
```

**修改定位与前后对照：** 根据下列函数名、配置项或导入位置定位；diff 仅供阅读，正负号不要复制进源码。对照以完成上一篇后的版本为准，请按 diff 修改已有文件。

```diff
--- backend/app/services/note_service.py（修改前）
+++ backend/app/services/note_service.py（修改后）
@@ -3,8 +3,9 @@
 from sqlalchemy import select
 from sqlalchemy.ext.asyncio import AsyncSession
 
+from app.core.failed_response import BusinessException
 from app.models.note import Note
-from app.schemas.models import NoteCreate
+from app.schemas.models import NoteCreate, NoteUpdate
 
 
 class NoteService:
@@ -42,5 +43,42 @@
         return list(result.scalars().all())
 
 
-# 【新增】服务对象不保存会话或用户状态，可以被各请求复用。
+    async def update_note(
+        self, db: AsyncSession, note_id: str, user_id: str, payload: NoteUpdate
+    ) -> Note | None:
+        note = await self.get_note(db, note_id, user_id)
+        if note is None:
+            return None
+        # 【新增 C02】只更新请求中明确给出的字段，保留其他值。
+        changes = payload.model_dump(exclude_unset=True)
+        if not changes:
+            raise BusinessException(code=4001, message="没有提交可修改字段")
+        for name, value in changes.items():
+            setattr(note, name, value)
+        await db.commit()
+        await db.refresh(note)
+        return note
+
+    async def delete_note(
+        self, db: AsyncSession, note_id: str, user_id: str
+    ) -> bool:
+        note = await self.get_note(db, note_id, user_id)
+        if note is None:
+            return False
+        await db.delete(note)
+        await db.commit()
+        return True
+
+    async def toggle_pin(
+        self, db: AsyncSession, note_id: str, user_id: str
+    ) -> Note | None:
+        note = await self.get_note(db, note_id, user_id)
+        if note is None:
+            return None
+        note.is_pinned = not note.is_pinned
+        await db.commit()
+        await db.refresh(note)
+        return note
+
+
 note_service = NoteService()
```

**整体解释：** 服务拿到用户 ID 和笔记 ID 后，先找出确实属于此人的记录，再只改请求明确交来的字段，提交后数据库才真正改变。删除与置顶也在这道归属检查后执行；找不到就停下，不会误动别人的笔记。更新先找到当前用户的记录，再对显式字段赋值；删除先确认同一归属，再提交删除；置顶先读当前状态，翻转后提交并刷新。setattr 的字段名并不是直接来自任意原始 JSON，而是来自 NoteUpdate 校验后的字段集合。未声明的客户端字段不会直接进入数据库对象。关键保护仍包括模型允许哪些字段，以及查询约束属于哪位用户。更新的 commit 把本次修改提交成一笔事务。对同一个 Session 里同一事务所做的修改，提交失败就不应继续走成功返回；get_db 接住异常回滚。响应生成阶段失败和提交前失败的含义不同，排错时要看失败发生在哪个动作。delete_note 的 db.delete 仍不等于永久删除，必须等 commit 成功。返回 bool 让路由区分“本次确实找到并删除”和“未找到目标”；重复删除不会再删出第二条数据。当前删除范围只有 notes 表。原项目还会联动图谱和回顾记录；这些资源尚未接入，所以本篇明确不声称“删除了所有向量和图关系”。等相应模块建立后再扩展同一个删除业务，不另外造一个互不关联的清理接口。置顶采用与参考业务相近的读后翻转方式，适合理解状态变化，但不是“任意并发都原子翻转”的保证。两个同时到达的请求可能基于同一旧值更新；后续需要高并发语义时考虑数据库表达式或行锁，不能仅凭用了 async 就认为已解决竞争。updated_at 由 ORM 更新语句维护，若新值与旧值相同可能不产生真正 UPDATE；数据库时间精度也可能让短时间内两次操作显示同一秒。验证应优先看业务字段，不能仅用时间字符串是否变化判断成功。

### 步骤 3：【修改】`backend/app/router/note_router.py`

**编辑文件的完整地址：**

```text
./backend/app/router/note_router.py
```

**修改定位与前后对照：** 根据下列函数名、配置项或导入位置定位；diff 仅供阅读，正负号不要复制进源码。对照以完成上一篇后的版本为准，请按 diff 修改已有文件。

```diff
--- backend/app/router/note_router.py（修改前）
+++ backend/app/router/note_router.py（修改后）
@@ -4,7 +4,7 @@
 
 from app.core.success_response import success_response
 from app.db.db_config import get_db
-from app.schemas.models import NoteCreate, NoteListResponse, NoteResponse
+from app.schemas.models import NoteCreate, NoteListResponse, NoteResponse, NoteUpdate
 from app.services.note_service import note_service
 from app.utils.auth_utils import get_current_user_id
 
@@ -44,3 +44,41 @@
     if note is None:
         return success_response(message="笔记不存在")
     return success_response(data=NoteResponse.model_validate(note))
+
+
+@note_router.put("/{note_id}")
+async def update_note(
+    note_id: str,
+    payload: NoteUpdate,
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> JSONResponse:
+    # 【新增 C03】HTTP 参数与依赖准备好后，交给服务完成修改。
+    note = await note_service.update_note(db, note_id, user_id, payload)
+    if note is None:
+        return success_response(message="笔记不存在")
+    return success_response(message="笔记更新成功", data=NoteResponse.model_validate(note))
+
+
+@note_router.put("/{note_id}/pin")
+async def toggle_pin(
+    note_id: str,
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> JSONResponse:
+    note = await note_service.toggle_pin(db, note_id, user_id)
+    if note is None:
+        return success_response(message="笔记不存在")
+    return success_response(message="置顶已更新", data=NoteResponse.model_validate(note))
+
+
+@note_router.delete("/{note_id}")
+async def delete_note(
+    note_id: str,
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> JSONResponse:
+    deleted = await note_service.delete_note(db, note_id, user_id)
+    if not deleted:
+        return success_response(message="笔记不存在")
+    return success_response(message="笔记删除成功")
```

**整体解释：** 路由像柜台：它从请求拿参数、从依赖拿用户与会话，再将工作单交给服务。服务完成更新、删除或置顶，路由把结果装进统一响应；HTTP 入口只负责协调，实际数据库动作留在服务层。增加三个路由处理函数，原创建、列表、详情完整保留。同一路径 /note/{note_id} 可以按 GET、PUT、DELETE 匹配不同处理函数；框架结合方法与路径判断，不是仅凭地址字符串。置顶使用 /{note_id}/pin，对应参考已有接口形状。路由没有自己拼 UPDATE/DELETE SQL，它只准备输入与依赖，把具体事务交给服务。与创建接口一致，输出经过 NoteResponse 再进成功响应工具。更新不存在的记录、删除不存在的记录继续返回“笔记不存在”的参考兼容消息和 data=null。空更新会从服务抛出 BusinessException，被第 02 篇处理为 HTTP 200、业务 code=4001；明确传 title=null 则在进入服务之前以 HTTP 422 拒绝。这两条失败路径发生阶段不同。不需要再修改 main.py，因为本篇在已被注册的 note_router 中声明新规则。保存并重载应用时重新构建这张规则表，主入口会把更新后的表注册进去；这不是运行时随手改路由列表就能自动传播的承诺。

## 4. 跟踪一次只改标题的请求

数据库中原记录包含 title、content、category、tags、is_pinned。请求只发 {"title":"新的标题"}，NoteUpdate 的实际字段集合只有 title，exclude_unset 只产生这个键。服务查到当前用户的记录，把 title 改掉，其他属性仍保留原值，然后提交与刷新。

现在换成 {"category":null}，实际字段集合包含 category，数据中也保留 None，于是分类被清空。若错误使用 exclude_none=True，这次清空请求会被误判成没有字段，行为与用户意图不符。

再换成 {"is_pinned":false}，False 必须保留，不能通过 `if value` 来筛选修改项；否则取消置顶会失效。判断字段是否提交，要看字段集合，不是看值的真假。

## 5. 准备一条专门用于本篇的测试笔记

不要对你想保留的笔记做删除演示。**执行位置：终端 B，复刻 backend；服务在终端 A 保持运行。**
```bash
cd "./backend"
```

如果提示符虽然显示 `(backend)`，但 `VIRTUAL_ENV` 实际指向上一级参考项目的 `backend/.venv`，先在这个终端执行：

```bash
deactivate
source "./backend/.venv/bin/activate"
printf '%s\n' "$VIRTUAL_ENV"
```

最后一行应打印包含 `MindWeave/backend/.venv` 的完整路径。`deactivate` 只退出当前 Python 虚拟环境，不会删除笔记或清空 `NOTE_ID` 这个 Shell 变量。若这个终端没有激活 Python 虚拟环境，跳过 `deactivate`，直接执行 `source`。下面的解析命令还明确使用复刻项目的 `./.venv/bin/python`，即使外层提示符有 `(base)` 也能选对解释器。

```bash
NOTE_ID=$(
  curl -sS -X POST http://127.0.0.1:8100/note/create \
    -H 'Content-Type: application/json' \
    -d '{"title":"第05篇操作练习","content":"用于修改和删除验证。","category":"study","tags":["lesson05"]}' \
  | ./.venv/bin/python -c 'import json,sys; print(json.load(sys.stdin)["data"]["id"])'
)
printf '%s\n' "$NOTE_ID"
```
应打印实际 UUID。后续命令在同一个终端 B 执行，变量只存在于这个 Shell；新开终端需要重新赋值。如果已经得到本篇专用的 UUID，就沿用现有的 `$NOTE_ID`，不要为了消除虚拟环境警告再次执行创建命令；重复创建会多一篇测试笔记。如果创建失败，先检查创建响应，不要带着空 id 继续操作。

### 5.1 只修改标题
```bash
curl -i -X PUT "http://127.0.0.1:8100/note/$NOTE_ID"   -H 'Content-Type: application/json'   -d '{"title":"已经修改的标题"}'
curl -i "http://127.0.0.1:8100/note/$NOTE_ID"
```
预期标题改变，正文、分类、标签仍保留。若它们全变成 null，先核对是否使用 exclude_unset=True，而不是直接把整个模型默认值写回数据库。

### 5.2 清空分类、切换置顶
```bash
curl -i -X PUT "http://127.0.0.1:8100/note/$NOTE_ID"   -H 'Content-Type: application/json'   -d '{"category":null}'
curl -i -X PUT "http://127.0.0.1:8100/note/$NOTE_ID/pin"
curl -i -X PUT "http://127.0.0.1:8100/note/$NOTE_ID/pin"
```
分类变成 null；置顶从 false 到 true，再回 false。需要直接设置具体状态时，普通更新接口也接受 is_pinned 字段。切换和设置是不同业务语义：重复“设置为 true”仍为 true，重复“切换”会再次翻转。

### 5.3 对照两种失败路径
```bash
curl -i -X PUT "http://127.0.0.1:8100/note/$NOTE_ID"   -H 'Content-Type: application/json' -d '{}'
curl -i -X PUT "http://127.0.0.1:8100/note/$NOTE_ID"   -H 'Content-Type: application/json' -d '{"title":null}'
```
第一个 HTTP 200 但 code=4001、message=没有提交可修改字段；第二个 HTTP 422，数据没有被改动。HTTP 200 不一定等于这项业务操作成功，这是项目的错误约定。

### 5.4 删除并再次读取
```bash
curl -i -X DELETE "http://127.0.0.1:8100/note/$NOTE_ID"
curl -i "http://127.0.0.1:8100/note/$NOTE_ID"
curl -i -X DELETE "http://127.0.0.1:8100/note/$NOTE_ID"
```
第一次删除返回“笔记删除成功”；之后读取与再次删除都返回“笔记不存在”。重启后仍不存在，说明删除已经提交，而不是仅从当前进程列表里拿掉了一项。

要手动重启，在终端 A 按 Control + C 后执行：
```bash
cd "./backend"
uv run uvicorn main:app --reload --host 127.0.0.1 --port 8100
```
## 6. 常见问题与排查线索

| 现象 | 优先检查 | 关键区别 |
|---|---|---|
| 只改标题却清空了正文 | exclude_unset 与默认 None | 未传不等于要清空 |
| category=null 清不掉分类 | 是否错误使用 exclude_none | 允许清空的字段必须保留显式 None |
| is_pinned=false 没有效果 | 是否用真假值过滤 changes | False 也是合法修改值 |
| 删除后重启又出现 | commit 与实际连接的库 | 内存删除不等于事务提交 |
| 新接口 404/405 | 路由是否保存、方法是否 PUT/DELETE | 路径与方法共同匹配 |
| 临时变量为空 | 终端 B 与创建响应 | Shell 变量不跨新终端自动传递 |

## 7. 完成核对与阶段边界

- [ ] 原创建、列表、详情功能仍通过。
- [ ] 局部修改只改变提交的字段，None 与 False 的语义正确。
- [ ] 空更新与非法 null 分别进入业务异常和输入校验路径。
- [ ] 删除提交后无法重新读取，置顶状态可观察。
- [ ] 所有查询与修改都沿 get_note 的 id+user_id 约束。

本篇没有新依赖，requirements.txt 不需要人为增加包。数据库表结构也没变，不需要删表重建。

下篇[分页、分类标签筛选与排序](06-note-pagination-filter-and-sort.md)会优化列表，不改变本篇 CRUD 接口路径。那时 list 的 total_count 将从“当前返回列表长度”升级为“筛选后的总条数”，便于前端分页。

**参考源码：** [笔记路由](../../../backend/app/router/note_router.py)、[请求模型](../../../backend/app/schemas/models.py)、[笔记业务服务](../../../backend/app/services/note_service.py)。本篇保留路径与核心字段，暂未接入限流、真实 JWT、AI、图谱和回顾联删，这些差异不能当作已完成能力。

### 本篇验证记录

**已执行流程与 HTTP 验证（2026-10-20，临时 SQLite）**：只改标题保留正文与标签；显式 category=null 能清空；is_pinned 的 True/False 均正确；两次置顶翻转恢复原值；空更新进入 HTTP 200/code=4001，非空列显式 null 返回 422；删除后读取及重复删除符合约定。两个测试用户的越界修改/删除没有改变目标数据。

正式复刻数据没有参与测试，也没有被删除。MySQL 事务、认证、实际并发锁行为仍待 Docker 运行后验证，本篇未声称完成并发原子置顶。

本轮临时验证记录：`/tmp/verification-results.json`。所有验证服务均已停止；正式 8100 服务及其源码不参与本轮变更。
