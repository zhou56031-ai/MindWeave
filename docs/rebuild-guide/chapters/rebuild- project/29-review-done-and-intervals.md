# 第 29 篇：标记完成回顾、间隔推进与并发保护

> 前置：第 28 篇完成后的复刻后端。本文是待操作教程，写作时对照了正式复刻目录和参考项目；文中的预期结果不是正式工程已实测的结果。
> 成果：POST /review/done/{note_id} 原子推进当前用户的一条到期回顾记录，避免并发点击让计数跳两次。
> 范围：只指导后端；前端继续直接使用已经复制的源码。新增文件给完整代码，修改文件只给本次 diff，不重复整份最终源码。

## 1. 本篇要接通的真实能力

第 28 篇能查询到期项目，但完成按钮如果只在前端把卡片移走，刷新又会出现。现在让后端按 note_id 和当前用户锁定回顾记录，计算下次到期时间，并在一个事务里更新计数、间隔和时间。参考项目采用 1、2、4、7、15、30 天的固定数组；本篇沿用这条清晰路线，同时处理双击和两个设备同时提交时的重复推进。

本篇从复刻项目现有代码继续，路径和导入均从下面这个固定目录算起。不要在参考仓库执行修改；那份源码用于比较接口与数据流。代码注释中【新增】标出本步新行为，diff 的正负号只用于定位，不要粘进 Python 文件。涉及账号或模型密钥时只用本机 `.env`，不把真实值写进教程或 Git。

**复刻根目录：**

```text
.
```

**本篇接口或产物契约：**

- `POST /review/done/{note_id}` 只操作令牌所属用户的笔记。
- 到期记录第一次完成后计数为 1，间隔按 `INTERVAL_DAYS[1]` 为 2 天；之后依次推进，超过数组末尾固定为 30 天。
- 未到期再次点击得到明确 409，不会把计数连续加二。
- 笔记或记录不存在统一 404；不返回另一账号是否有这条记录。

**本篇与参考实现的差异：** 参考实现先读再 UPDATE，双设备同时点可能重复推进；本篇在 MySQL 行锁内判断到期状态，使用数据库约束保护同一条回顾记录。

**技术路线阅读：** [Q14：固定间隔回顾与其他调度路线](technology-routes/Q14-spaced-review-schedule.md)。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 路径 | 本步职责 |
|---:|---|---|---|
| 1 | 【修改】 | `backend/app/schemas/models.py` | 定义完成操作返回的进度字段 |
| 2 | 【修改】 | `backend/app/services/review_service.py` | 锁定归属记录并只对到期项目推进 |
| 3 | 【修改】 | `backend/app/router/review_router.py` | 让回顾页完成按钮调用服务 |

先看清楚上表：新文件的父目录若已存在就复用；步骤之间的 import 按顺序出现。每做完一个文件就做该步的小检查，不要把所有代码贴完才第一次启动。修改已有文件时请按 diff 的上下文搜索函数名或配置项，行号只供参考，因为上一章或你自己的改动可能改变行号。

## 3. 按顺序修改文件与验证

### 步骤 1：【修改】 `backend/app/schemas/models.py`

**文件职责：** 定义完成操作返回的进度字段

**编辑文件的完整地址：**

```text
./backend/app/schemas/models.py
```

**修改定位与前后对照：** 搜索代码块中的原函数或配置项，按 `-` 删除旧行、按 `+` 增加新行。只展示本篇变更。

```diff
@@
 class ReviewTodayResponse(BaseModel):
     reviews: list[ReviewItemResponse]
     total_count: int
+
+
+class ReviewDoneResponse(BaseModel):
+    success: bool
+    message: str
+    review_count: int
+    interval_days: int
+    next_review_at: datetime
```

**整体解释：** 完成响应像新的预约小票：告诉前端“已完成”、累计次数、下次间隔和具体时间。字段由后端更新后的数据库对象提供，不让前端自己把旧数加一；这样两个设备都以服务端最终状态为准。时间写成 datetime 再经 JSON 编码，避免各端自己拼格式。

**工程位置与触发时刻：** 服务提交后构造模型，路由由 success_response 包装。

**完成这一小步的判断：** 字段能被 Pydantic 验证，next_review_at 不是随意字符串。

**如果这里失败：** 若响应缺 next_review_at，检查服务是否在提交前/后用旧对象构造。

### 步骤 2：【修改】 `backend/app/services/review_service.py`

**文件职责：** 锁定归属记录并只对到期项目推进

**编辑文件的完整地址：**

```text
./backend/app/services/review_service.py
```

**修改定位与前后对照：** 搜索代码块中的原函数或配置项，按 `-` 删除旧行、按 `+` 增加新行。只展示本篇变更。

```diff
@@
-from sqlalchemy import select
+from datetime import timedelta
+
+from fastapi import HTTPException
+from sqlalchemy import select
@@
-from app.schemas.models import ReviewItemResponse, ReviewTodayResponse
-from app.services.review_schedule import utc_naive_now
+from app.schemas.models import ReviewDoneResponse, ReviewItemResponse, ReviewTodayResponse
+from app.services.review_schedule import interval_for_completed_count, utc_naive_now
@@ class ReviewService:
+    async def mark_done(
+        self, db: AsyncSession, user_id: str, note_id: str
+    ) -> ReviewDoneResponse:
+        result = await db.execute(
+            select(ReviewRecord)
+            .join(Note, ReviewRecord.note_id == Note.id)
+            .where(
+                ReviewRecord.note_id == note_id,
+                ReviewRecord.user_id == user_id,
+                Note.user_id == user_id,
+            )
+            .with_for_update()
+        )
+        record = result.scalar_one_or_none()
+        if record is None:
+            raise HTTPException(status_code=404, detail="回顾记录不存在")
+        now = utc_naive_now()
+        if record.next_review_at > now:
+            raise HTTPException(status_code=409, detail="尚未到回顾时间")
+        record.review_count += 1
+        record.interval_days = interval_for_completed_count(record.review_count)
+        record.last_reviewed_at = now
+        record.next_review_at = now + timedelta(days=record.interval_days)
+        await db.commit()
+        return ReviewDoneResponse(
+            success=True, message="已标记回顾",
+            review_count=record.review_count,
+            interval_days=record.interval_days,
+            next_review_at=record.next_review_at,
+        )
```

**整体解释：** 这里的关键不是给整数加一，而是在数据库锁住当前用户的回顾行后，再决定它是否仍到期。两个设备同时点：第二个事务要等第一个提交，随后读到已经推迟的 next_review_at，返回 409；它不会重复加一次。JOIN Note 并双重过滤归属避免用别人的 note_id 推进。一次提交把 count、interval、last 和 next 四个字段作为同一状态转移保存。若中途数据库失败，请求会话回滚。

**工程位置与触发时刻：** POST /review/done/{id} 调用 mark_done 时执行 SELECT ... FOR UPDATE；锁持续到 commit 或回滚。

**完成这一小步的判断：** 第一次到期完成得到 count=1、interval=2，立即再试得 409。

**如果这里失败：** 若并发两次都成功，检查 MySQL 引擎、实际 SQL 是否带 FOR UPDATE、事务是否在读取后提前结束。

### 步骤 3：【修改】 `backend/app/router/review_router.py`

**文件职责：** 让回顾页完成按钮调用服务

**编辑文件的完整地址：**

```text
./backend/app/router/review_router.py
```

**修改定位与前后对照：** 搜索代码块中的原函数或配置项，按 `-` 删除旧行、按 `+` 增加新行。只展示本篇变更。

```diff
@@
 @review_router.get("/today")
 async def get_today_reviews(
@@
     return success_response(data=await review_service.today(db, user_id))
+
+
+@review_router.post("/done/{note_id}")
+async def mark_reviewed(
+    note_id: str,
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> JSONResponse:
+    result = await review_service.mark_done(db, user_id, note_id)
+    return success_response(message="已标记回顾", data=result)
```

**整体解释：** 路由承接前端传来的 note_id，但真正的用户身份由 JWT 依赖决定。它不根据请求正文接收 user_id，也不在这里计算下次日期；这些都留给服务和调度函数。数据库提交成功后才包装“已标记回顾”，避免只因为 HTTP 路由被调用就让页面以为学习进度持久化了。

**工程位置与触发时刻：** URL 中的 note_id 只是目标编号，服务查询会同时限制归属。

**完成这一小步的判断：** OpenAPI 出现 POST /review/done/{note_id}，正确 token 可进入服务。

**如果这里失败：** 404 可能是路由未注册或记录不存在，看响应形状区分；409 代表尚未到期。

## 4. 请求和状态如何穿过这些文件

下面只追踪本篇真正涉及的调用链，帮助把刚改的文件连起来；这段解释不需要复制进源码。

1. **请求：** DailyReview 对 note_id 发送 POST，JWT 指明当前用户。
2. **查找：** 服务通过 ReviewRecord 与 Note 的 JOIN、双 user_id 条件锁定唯一行。
3. **等待：** 并发第二请求在同一行上等待，直到第一个提交或回滚。
4. **判断：** 拿到行后以统一 UTC 时钟确认当前是否到期。
5. **推进：** 成功时 count 加一，用新 count 查固定间隔数组，更新四个状态字段。
6. **提交：** MySQL 一次 commit 后释放锁。
7. **复读：** 下一次 GET /review/today 因到期时间已推迟而不再返回它。

**事务与隔离边界：** 本篇只保护单条 MySQL 回顾行；它不会自动阻止一个用户同时完成不同笔记，也不需要全局锁。HTTP 409 是业务上的“这条记录当前不能再推进”，不是数据库崩溃。固定间隔与个人记忆强度无关，后续若引入评分式调度必须同时修改模型与迁移。

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

**核对“完成次数”与数组索引的含义**：`./backend/app/services/review_schedule.py`。在写 UPDATE 前先固定规则：completed_count=0 对应初始 1 天，完成第一次后传入 1 对应 2 天。若把旧计数传进去，第一次完成还会安排 1 天，和期望不符。这个纯函数检查让 off-by-one 错误在未碰数据库时先暴露。

可用的定位或请求片段：

```bash
uv run python -c "from app.services.review_schedule import interval_for_completed_count; print([interval_for_completed_count(n) for n in range(8)])"
```

观察点：应输出 1,2,4,7,15,30,30,30。 若不符合，若顺序不符，先修正调度定义和本篇预期，不要给路由增加特殊分支。

**确认读写同一行的唯一性**：`./backend/app/models/review_record.py`。并发保护需要明确锁的对象。唯一键让同一个用户、同一篇笔记只有一条回顾进度；否则两个相同 note_id 的行可能被不同请求各锁一条，整个算法就失去单一状态来源。这里读取上一步建立的模型，确认没有误把标题或 email 当作唯一键。

可用的定位或请求片段：

```bash
rg -n "uq_review_user_note|note_id|next_review_at" backend/app/models/review_record.py
```

观察点：可见 user_id+note_id 唯一键，数据库 DDL 中也应有该约束。 若不符合，如果正式库是旧表，create_all 不会补 UNIQUE，需先处理迁移。

**核对请求级会话的回滚路径**：`./backend/app/db/db_config.py`。把数据库行锁想成临时占用柜台：成功提交会释放，异常回滚也应释放。get_db 在路由报 HTTPException 时进入 except 并 rollback；这点对 404/409 后及时释放锁很关键。若某个调用方自己吞掉异常而不回滚，连接可能带着未完成事务回池。

可用的定位或请求片段：

```bash
rg -n "async def get_db|yield session|rollback" backend/app/db/db_config.py
```

观察点：可见 yield 和异常 rollback；服务只提交本次状态。 若不符合，若连接池被耗尽，检查异常路径是否正确关闭会话。

**先验证不存在目标返回 404**：`./backend/app/router/review_router.py`。先测失败边界能防止“所有 POST 都返回成功”的假实现。这个 ID 不可能匹配本人回顾行，服务应该抛 404，且不会更新任何记录。返回码与业务消息由统一 HTTP 异常处理决定；不要只看 JSON 内部 code 而忽略 HTTP 状态。

可用的定位或请求片段：

```bash
curl -i -X POST http://127.0.0.1:8100/review/done/not-a-real-id -H "Authorization: Bearer $RAG_TOKEN"
```

观察点：HTTP 404，当前用户的回顾计数不变。 若不符合，若 200，检查服务是否在 record is None 时仍返回 success_response。

**在专用临时记录上验证首次完成**：`./backend/app/services/review_service.py`。本步先把临时回顾行 next_review_at 调到当前 UTC 之前，再调用接口。完成后用数据库读 review_count、interval_days、last_reviewed_at 和 next_review_at 四个字段。它们应一起变化，不只看响应；如果只改了内存对象没有 commit，刷新后会恢复旧值。

可用的定位或请求片段：

```text
POST /review/done/<临时笔记ID>
```

观察点：count 从 0 到 1，interval 为 2，下次约为两天后。 若不符合，若 409，检查临时记录是否真正到期；不要调整生产用户的学习进度。

**验证重复点击与并发只推进一次**：`./backend/app/services/review_service.py`。前端按钮可能双击，两个浏览器也可能几乎同时提交。本篇设计要求只有第一个到期请求成功，其余请求在拿到锁后发现尚未到期而返回 409。你应比较数据库最终 count，不要把“有一个请求失败”当成异常需要重试到成功。

可用的定位或请求片段：

```text
POST /review/done/<同一临时笔记ID> twice
```

观察点：重复请求后 count 仍为 1；并发组也只增加一次。 若不符合，若均成功，确认不是对两个不同 note_id 发请求；再看实际数据库隔离和 FOR UPDATE。

**从今日列表核对已完成项目消失**：`./backend/app/router/review_router.py`。完成按钮的可见结果不是数据库返回一句“成功”而已。由于 next_review_at 已推迟两天，同一笔记应从第 28 篇的 today 列表消失；下次到期后又会出现。这一读后验收把写入与查询串起来，也能发现 due_at 算错或查询时钟不一致。

可用的定位或请求片段：

```bash
curl -sS http://127.0.0.1:8100/review/today -H "Authorization: Bearer $RAG_TOKEN" | python3 -m json.tool
```

观察点：列表不再包含该临时 note_id，其他到期记录不受影响。 若不符合，若仍出现，查事务 commit、next_review_at 值、today 的时间比较。

### 验收 1：确认接口存在

**准备与操作：** 重载应用。

```bash
curl -sS http://127.0.0.1:8100/openapi.json | python3 -m json.tool
```

**期望结果：** 路径中有 POST /review/done/{note_id}。

**为什么要验这一项：** 区分路由 404 与业务 404。

**不符合时从哪里查：** 无路径先看 main 路由登记和重载日志。

### 验收 2：匿名拒绝

**准备与操作：** 不带 JWT 调用。

```text
POST /review/done/<临时ID>
```

**期望结果：** HTTP 401。

**为什么要验这一项：** 用户进度不能匿名修改。

**不符合时从哪里查：** 若返回 200，检查依赖注入。

### 验收 3：他人 ID 拒绝

**准备与操作：** 用账号 B token 调账号 A 的临时笔记。

```text
POST /review/done/<A_NOTE_ID>
```

**期望结果：** HTTP 404，A 的计数不变。

**为什么要验这一项：** 不透露另一用户的记录是否存在。

**不符合时从哪里查：** 查两个 user_id 条件。

### 验收 4：未到期拒绝

**准备与操作：** 新建笔记后立即请求。

```text
POST /review/done/<NEW_NOTE_ID>
```

**期望结果：** HTTP 409，计数仍为 0。

**为什么要验这一项：** 避免用户或重试把间隔跳过。

**不符合时从哪里查：** 如果成功，检查 next_review_at 比较符号。

### 验收 5：到期后成功

**准备与操作：** 把专用记录 due_at 调到过去。

```sql
UPDATE review_records SET next_review_at=UTC_TIMESTAMP() - INTERVAL 1 MINUTE WHERE note_id="<临时ID>";
```

**期望结果：** 再 POST 得成功。

**为什么要验这一项：** 验证正向状态转移。

**不符合时从哪里查：** 不要对现有真实笔记做此 UPDATE。

### 验收 6：首次间隔

**准备与操作：** 读提交后的数据。

```sql
SELECT review_count,interval_days,next_review_at FROM review_records WHERE note_id="<临时ID>";
```

**期望结果：** count=1，interval_days=2，next 约两天后。

**为什么要验这一项：** 防止旧计数/新计数混用。

**不符合时从哪里查：** 查 interval_for_completed_count 的入参。

### 验收 7：双击保护

**准备与操作：** 立刻重复请求。

```text
POST /review/done/<临时ID>
```

**期望结果：** HTTP 409，计数保持 1。

**为什么要验这一项：** 验证幂等效果边界。

**不符合时从哪里查：** 若计数跳两次，看是否缺 due_at 判断。

### 验收 8：两个连接同时提交

**准备与操作：** 用两个请求工具同时对同一临时 ID 发 POST。

```text
并行两次 POST /review/done/<临时ID>
```

**期望结果：** 最多一个成功，最终 count 只加一。

**为什么要验这一项：** 验证行锁真实发挥作用。

**不符合时从哪里查：** 先把记录重新调到期，再看 MySQL 锁与事务。

### 验收 9：列表刷新

**准备与操作：** 完成后再 GET today。

```text
GET /review/today
```

**期望结果：** 刚完成记录消失，其他记录保留。

**为什么要验这一项：** 跨接口核对状态变化。

**不符合时从哪里查：** 查 now/due_at 时区一致性。

### 验收 10：清理临时数据

**准备与操作：** 删除本篇笔记。

```text
DELETE /note/<临时ID>
```

**期望结果：** 回顾行级联删除。

**为什么要验这一项：** 避免影响未来每日列表。

**不符合时从哪里查：** 如果仍存在，检查外键 DDL。

## 6. 深入动手与状态核对

### 把完成动作视为一次状态机转移

回顾行有两个关键状态：到期（`next_review_at <= now`）与未到期（`next_review_at > now`）。完成动作只允许从到期状态转到下一次未到期状态；它不是任意点击就加一的计数按钮。拿一条临时记录，把其预约时间调整到过去一分钟，调用一次 `/review/done/{note_id}`。应该同时看到四个变化：`review_count` 从 0 到 1，`interval_days` 变 2，`last_reviewed_at` 记录此次时间，`next_review_at` 变成此次时间约两天后。然后立刻用相同令牌和 ID 再调用，应该得到 409，四个字段不再变。这样才能证明“完成一次”，而不是仅仅证明路由存在。

为什么 `with_for_update()` 要和“是否到期”判断放在同一个事务？想象手机和电脑同时打开同一张卡。若先不锁行，两边都读到旧的 `review_count=0`，都判断已经到期，然后都提交新状态；即使最终值看起来只加了一次，两个请求都可能返回成功并触发额外副作用。锁住同一行后，第二个请求等待第一个提交，拿到的已是新的到期时间，因而明确返回 409。数据库唯一键保证用户与笔记只有一条进度行；否则两个请求可能锁到两条不同记录。这里依赖 MySQL 的行锁和事务，不是 Python 进程内的 `asyncio.Lock`；多个 Uvicorn 进程也应受同一数据库约束。

服务应在锁住行后再取得当前 UTC 时间。若时间在排队等待锁之前就算好，第二个请求可能用已经过期的判断基准。当前代码只锁回顾行，两个不同笔记可以并行完成。第一次完成用增加后的 `review_count=1` 查间隔，得到 2 天；不能用旧值 0，否则第一次仍是 1 天。超过固定数组最后一项时持续使用 30 天，不应抛索引错误。`last_reviewed_at` 与 `next_review_at` 都围绕同一个 `now` 计算，避免一次请求里前后时间不一致。

### 失败时检查的对象

404 表示这个用户查不到该笔记对应的回顾行，不能因此判断“系统里绝无这个 ID”；这种不泄露存在性的响应是权限边界。409 表示找到了自己的行，但当前尚未到期。这两种业务错误都不应把 session 留在未完成事务里，否则下一请求可能占用连接或持有锁。既有 `get_db` 异常回滚与 `async with` 关闭会话，是释放资源的一部分。数据库错误则要看服务日志，不能都转成 409。

验收并发时只操作本篇专用的到期记录：先调到期，再几乎同时发送两个 POST，记录每个 HTTP 状态和最终数据库计数；“一个成功、一个 409，计数只增加一次”是清晰结果。若两次都 409，先核对调整时间是否写入正确库；若两次都成功，检查是否真是同一个 `note_id`、`SELECT ... FOR UPDATE` 是否在实际 SQL 中，以及是否在判断前提前提交。完成后再次 GET 今日列表，临时卡片应消失，这把写路径与读路径接在一起。

### 用连续两次完成解释“幂等效果”与真正幂等的差别

本篇重复点击返回 409、数据库不变，达到了“不会多推进一次”的效果；但两个 HTTP 响应不同，严格说它不是“同一个请求重发得到完全相同响应”的幂等接口。面试里要说清这个边界。若前端网络断开，用户不知道第一次点击是否成功，重试得到 409时应该重新 GET 今日列表或记录详情确认状态，而不是把 409 当成又一次失败并反复点击。若产品要求重试返回第一次成功结果，可在请求里加幂等键并保存结果，但这是另一套状态管理，本篇没有实现。

`SELECT FOR UPDATE` 锁的是数据库行，不是整个用户或整张表。两个不同笔记的回顾可以同时完成；同一笔记的第二请求等待。这要求 SQL 真正处在一个活跃事务里，也要求真实数据库是支持行锁的 MySQL/InnoDB。把服务换成 SQLite 测试可能得到不同锁行为，不能用 SQLite 上的通过证明生产并发正确。单元测试可以验证计算规则，并发正确性要用两条真实数据库连接和相同临时 note_id 检验。

时间过期条件必须在拿锁之后检查。假设第二请求排队时记录已由第一请求推迟到两天后，若代码沿用排队前读到的旧对象，就可能再次推进。SQLAlchemy 在同一会话内是否缓存对象也值得留意：本篇只做一次带锁查询，不先加载同一行的旧 ORM 实例，能避免身份映射缓存造成误读；若日后服务先查询再锁，应显式刷新或核对实际行为。所有状态字段在同一 commit 中更新，若写入中途失败，回滚后不应出现“计数加了、时间没变”的组合。

到期时间用于提醒，`last_reviewed_at` 用于历史解释。即使下一次间隔总是 30 天，也不能只把 `next_review_at` 增加 30 天而不更新完成次数和上次时间；否则前端或未来算法无法解释用户已复习多少次。相反，用户手动改了笔记正文是否应重置回顾次数，当前没有规则，不能让 `NoteService.update_note` 暗中改回顾行。要先做产品定义，再以可测试的状态转移实现。

### 为并发演练建立可重复的起点

不要直接对账号里的真实回顾卡试验。新建专用临时笔记，在复刻 MySQL 里只按其 note_id 把 `next_review_at` 调到 UTC 当前时刻之前；确认 `review_count=0`、`interval_days=1`。随后同时发两次 POST，记录两份 HTTP 响应、最终数据库行和再次 GET 今日列表的结果。理想的组合是一次 200、一次 409，数据库 `review_count=1`、`interval_days=2`，列表不再显示这张卡。若两个响应先后到达，不要求哪个客户端先成功；只要求最终状态只推进一次。

如果要第二次重复演练，把同一专用记录重新设为到期，先明确记录当前 count 应为 1，再并发发送两个 POST。成功后 count 应为 2，下一间隔应为 4 天。这比只测第一次更能发现“每次都从固定 2 天开始”或把旧计数传给调度函数的错误。演练后删除临时笔记，让级联一并移除回顾行。若并发第二个请求偶尔卡住，记录 MySQL 活跃事务、行锁等待和连接池使用情况；不要简单把超时调成无限大。

需要区分三个错误入口。未带令牌的 401 发生在鉴权依赖；他人或不存在 note_id 的 404 发生在授权范围查询；未到期的 409 发生在查到本人回顾行之后。三种情况都不应该改变计数或下次时间。把所有错误都捕获成 200 并在 JSON 里写“失败”，会让前端、监控和重试策略失去清楚的 HTTP 信号。当前统一异常处理保留相应状态码，验收时同时看响应头与业务体。

### 行锁等待时的具体时间线

请求一进入服务，SELECT 命中到期回顾行并获取锁；它计算新的间隔、更新四个字段，提交后释放锁。请求二几乎同时进入，停在同一行的锁等待处。请求一提交后，请求二继续，拿到新的 `next_review_at`，发现它在未来，返回 409 并由请求会话回滚、释放连接。若第二个请求用的是另一篇笔记，它不应等待第一行；这能帮助确认不是误用了全局锁。测试时两请求要使用同一 note_id 和同一账号，缺任何一个条件都不能证明单行并发保护。

在数据库级别，锁必须保持到 commit/rollback。若 service 在 SELECT 后先 `commit()`，再修改对象，锁已经释放，后续计算失去保护。若把 `with_for_update()` 写在查询链上却使用了不支持的测试数据库，代码可以运行但语义不一致。验收要在真实复刻 MySQL 上做，必要时打开 SQLAlchemy 语句日志确认实际执行 SQL 中有 `FOR UPDATE`。日志只记录参数化 SQL 和测试 ID，不记录 JWT 或私人正文。

如果服务异常导致连接池满，应检查每个请求是否通过 `get_db` 独立拿会话、异常是否回滚、是否有长时间不提交的事务。不要把 `pool_size` 从 5 直接改成很大来掩盖锁未释放。行锁只保护同一条回顾进度，不解决两个用户共用同一笔记的共享编辑语义；当前笔记按用户独立拥有，权限查询用本人 Note 与本人 ReviewRecord 双重过滤。

## 7. 工程面试思考

回答时要指向本篇具体文件、数据库约束或接口结果，区分当前已实现、验证时才可能观察到的结果与未来扩展。这里讨论设计判断，不背诵通用定义。

**面试官：为什么用 SELECT ... FOR UPDATE，而不直接在 Python 加锁？**

Python 锁只能保护单个进程；Uvicorn 多 worker 或两台服务器不共享它。数据库行锁覆盖访问同一 MySQL 行的事务。锁住后必须重新判断到期，不能用锁前读到的旧状态继续更新。

**面试官：HTTP 重试应该返回什么？**

同一条记录已推迟到未来时返回 409，客户端可刷新 today 列表。若产品要求真正幂等且重复请求也返回第一次结果，需要客户端提供幂等键并存储结果；当前的“计数不重复推进”只保证状态不被重复改变。

**面试官：固定间隔法有什么局限？**

所有笔记都按相同数组推进，不参考用户答题难度。它简单、可解释、可测试，适合作为初版；若改为 SM-2 或 FSRS，需要增加评分输入与更多状态字段，并对历史记录做迁移，不能只换一个数组。

**面试官：数据库故障发生在更新前后怎么办？**

提交前异常会回滚，计数不变；提交完成但 HTTP 响应丢失时，客户端可能以为失败，重试会得到 409。应通过 GET today 或单条记录查询确认最终状态，不能因为网络失败直接再加一次。

## 8. 常见故障的定位顺序

- **始终 409：** 新建记录默认明天到期；用专用测试行人为设到期。
- **count 跳两次：** 检查 FOR UPDATE、事务持续范围及 due_at 再判断。
- **拿不到锁：** 排查长事务，限制同一会话里的外部 API 调用；当前服务不调用模型。
- **跨用户成功：** 检查 JOIN Note 的用户范围和 ReviewRecord 用户范围。
- **日期偏移：** 统一 UTC-naive，别在一处用本地 datetime.now()。

## 9. 本篇边界和下一篇

本篇完成回顾记录的读写闭环。第 30 篇先建立统一的 DeepSeek 调用边界，随后第 31 篇用真实模型为回顾页生成选择题。

本篇没有修改前端文件。新代码完成并经过你本机的验证后，才把它记为你亲手完成；仅阅读教程、助手先前的隔离检查或接口文档出现新路径，都不能代替真实执行。
