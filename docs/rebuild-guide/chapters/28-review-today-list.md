# 第 28 篇：今日回顾列表与用户隔离查询

> 前置：第 27 篇完成后的复刻后端。本文是待操作教程，写作时对照了正式复刻目录和参考项目；文中的预期结果不是正式工程已实测的结果。
> 成果：GET /review/today 从 review_records 与 notes 读取当前用户到期的笔记，并按前端需要的字段返回。
> 范围：只指导后端；前端继续直接使用已经复制的源码。新增文件给完整代码，修改文件只给本次 diff，不重复整份最终源码。

## 1. 本篇要接通的真实能力

第 27 篇已经在创建笔记时给它配了回顾行，但页面仍不知道今天该显示哪些。现在要把“回顾行的到期时间”与“笔记标题和内容”在 MySQL 中连接，按当前令牌的用户范围筛出真正到期的项目。这个接口只读，不应在列表请求中偷偷推进复习进度，也不应让别人的笔记因相同 note_id 或错误 JOIN 混进来。

本篇从复刻项目现有代码继续，路径和导入均从下面这个固定目录算起。不要在参考仓库执行修改；那份源码用于比较接口与数据流。代码注释中【新增】标出本步新行为，diff 的正负号只用于定位，不要粘进 Python 文件。涉及账号或模型密钥时只用本机 `.env`，不把真实值写进教程或 Git。

**复刻根目录：**

```text
.
```

**本篇接口或产物契约：**

- `GET /review/today` 需要 Bearer JWT，响应仍包在 `{code,message,data}` 中。
- `data.reviews` 是列表，`data.total_count` 与列表长度一致；每条包含 review_id、note_id、title、content_preview、tags、category、review_count、last_reviewed_at、interval_days。
- 仅显示 `next_review_at <= 当前 UTC` 的当前用户记录；以到期时间、记录 ID 稳定排序。
- 没有到期笔记时返回空数组和 0，不把它当作服务错误。

**本篇与参考实现的差异：** 参考服务同样 JOIN 回顾记录与笔记；本篇多加双表 user_id 条件与稳定排序，并把响应形状写进 Pydantic，减少误传他人数据和字段漂移。

**技术路线阅读：** 回顾间隔选型继续看 [Q14](technology-routes/Q14-spaced-review-schedule.md)；本篇主要关注 JOIN 与用户隔离。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 路径 | 本步职责 |
|---:|---|---|---|
| 1 | 【修改】 | `backend/app/schemas/models.py` | 给今日回顾列表定义明确的输出结构 |
| 2 | 【新增文件】 | `backend/app/services/review_service.py` | 执行双表、双用户范围的到期查询 |
| 3 | 【新增文件】 | `backend/app/router/review_router.py` | 接入今日列表的 HTTP 路径 |
| 4 | 【修改】 | `backend/main.py` | 把回顾路由组登记到 FastAPI 应用 |

先看清楚上表：新文件的父目录若已存在就复用；步骤之间的 import 按顺序出现。每做完一个文件就做该步的小检查，不要把所有代码贴完才第一次启动。修改已有文件时请按 diff 的上下文搜索函数名或配置项，行号只供参考，因为上一章或你自己的改动可能改变行号。

## 3. 按顺序修改文件与验证

### 步骤 1：【修改】 `backend/app/schemas/models.py`

**文件职责：** 给今日回顾列表定义明确的输出结构

**编辑文件的完整地址：**

```text
./backend/app/schemas/models.py
```

**修改定位与前后对照：** 搜索代码块中的原函数或配置项，按 `-` 删除旧行、按 `+` 增加新行。只展示本篇变更。

```diff
@@
 class MD5ListResponse(BaseModel):
     records: list[MD5Record]
     total_count: int
+
+
+class ReviewItemResponse(BaseModel):
+    review_id: str
+    note_id: str
+    title: str
+    content_preview: str
+    tags: list[str] = Field(default_factory=list)
+    category: str = ""
+    review_count: int
+    last_reviewed_at: datetime | None = None
+    interval_days: int
+
+
+class ReviewTodayResponse(BaseModel):
+    reviews: list[ReviewItemResponse]
+    total_count: int
```

**整体解释：** 响应模型像出馆清单：里面只有回顾页要展示的字段，不把 Note 全文和 ORM 状态一次扔给浏览器。tags、category 在早期笔记可能为空，响应统一为空列表和空字符串；content_preview 截断，避免一页待回顾笔记把全部正文传回来。模型把 review_id 和 note_id 明确分开，后续 done 接口使用 note_id，不会错拿回顾行的主键。

**工程位置与触发时刻：** 路由在服务返回后交给 success_response 编码；模型构造时就能发现字段类型不匹配。

**完成这一小步的判断：** 对空列表与非空列表都能生成固定结构，日期转换为 ISO 字符串。

**如果这里失败：** 若 Pydantic 报 tags 类型错误，检查服务是否忘记把 None 转成 []。

### 步骤 2：【新增文件】 `backend/app/services/review_service.py`

**文件职责：** 执行双表、双用户范围的到期查询

**编辑文件的完整地址：**

```text
./backend/app/services/review_service.py
```

**完整文件内容：**

```python
"""回顾列表与后续完成操作。"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.note import Note
from app.models.review_record import ReviewRecord
from app.schemas.models import ReviewItemResponse, ReviewTodayResponse
from app.services.review_schedule import utc_naive_now

class ReviewService:
    async def today(self, db: AsyncSession, user_id: str) -> ReviewTodayResponse:
        result = await db.execute(
            select(ReviewRecord, Note)
            .join(Note, ReviewRecord.note_id == Note.id)
            .where(
                ReviewRecord.user_id == user_id,
                Note.user_id == user_id,
                ReviewRecord.next_review_at <= utc_naive_now(),
            )
            .order_by(ReviewRecord.next_review_at.asc(), ReviewRecord.id.asc())
        )
        reviews = [ReviewItemResponse(
            review_id=record.id,
            note_id=note.id,
            title=note.title,
            content_preview=(note.content or "")[:200],
            tags=note.tags or [],
            category=note.category or "",
            review_count=record.review_count,
            last_reviewed_at=record.last_reviewed_at,
            interval_days=record.interval_days,
        ) for record, note in result.all()]
        return ReviewTodayResponse(reviews=reviews, total_count=len(reviews))

review_service = ReviewService()
```

**整体解释：** 服务像值班员从“预约回顾表”找今天到期的卡片，再去“笔记表”取书名与内容摘要。`join` 确保没有笔记的孤儿记录不会展示；两个 user_id 条件确保关联双方都属于请求用户。排序先按到期时间、再按 ID，即使多条在同一秒到期，列表顺序也稳定。服务只查询，不修改 review_count，不提交事务。

**工程位置与触发时刻：** GET /review/today 调用 today 时才执行 SELECT；请求依赖提供 user_id 与会话。

**完成这一小步的判断：** 同一用户只见自己的到期行，preview 最多 200 字符。

**如果这里失败：** 若列表意外为空，先查 next_review_at 与 UTC 当前时间，再查 JOIN 与两个 user_id，而不是直接把过滤去掉。

### 步骤 3：【新增文件】 `backend/app/router/review_router.py`

**文件职责：** 接入今日列表的 HTTP 路径

**编辑文件的完整地址：**

```text
./backend/app/router/review_router.py
```

**完整文件内容：**

```python
"""回顾页面的 HTTP 接口。"""
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.success_response import success_response
from app.db.db_config import get_db
from app.services.review_service import review_service
from app.utils.auth_utils import get_current_user_id

review_router = APIRouter(prefix="/review", tags=["review"])

@review_router.get("/today")
async def get_today_reviews(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return success_response(data=await review_service.today(db, user_id))
```

**整体解释：** 路由只负责把 HTTP 世界接到业务查询。JWT 依赖先确认身份，数据库依赖提供本请求会话；它们准备好后，路由把当前用户编号交给 review_service.today。服务已完成用户过滤，路由再统一包装响应。这样前端不需要传 user_id，任何手工附带的 user_id 参数也不会改变服务查询范围。

**工程位置与触发时刻：** 应用注册路由后，GET /review/today 才会触发函数；模块导入时不会查询所有用户的记录。

**完成这一小步的判断：** OpenAPI 有 GET /review/today；无令牌请求被拒绝。

**如果这里失败：** 若收到 404，先看 main.py 是否 include_router；若 401，先看 token 和 Redis，不要修改 SELECT。

### 步骤 4：【修改】 `backend/main.py`

**文件职责：** 把回顾路由组登记到 FastAPI 应用

**编辑文件的完整地址：**

```text
./backend/main.py
```

**修改定位与前后对照：** 搜索代码块中的原函数或配置项，按 `-` 删除旧行、按 `+` 增加新行。只展示本篇变更。

```diff
@@
 from app.router.note_template_router import note_template_router
+from app.router.review_router import review_router
 from app.router.user import user_router
@@
 app.include_router(note_template_router)
+app.include_router(review_router)
 register_exception_handlers(app)
```

**整体解释：** 新建路由文件像写好接待窗口的规则，`include_router` 才把它挂上总台。这里和笔记、知识路由并列注册，让 `/review/today` 进入同一 FastAPI 应用与异常处理体系。注册只发生在进程启动导入 main 时，不会自动执行今日查询。

**工程位置与触发时刻：** Uvicorn 重载 main:app 时重新登记所有路由；HTTP 请求进来后才调用依赖和服务。

**完成这一小步的判断：** /openapi.json 中有路径，旧路径保持可用。

**如果这里失败：** 若路由缺失，检查 import 拼写与 Uvicorn 是否加载复刻 backend 的 main.py。

## 4. 请求和状态如何穿过这些文件

下面只追踪本篇真正涉及的调用链，帮助把刚改的文件连起来；这段解释不需要复制进源码。

1. **入口：** 前端 DailyReview 请求 GET /review/today；请求头携带 JWT。
2. **鉴权：** get_current_user_id 解析并检查令牌状态，得到用户 ID。
3. **会话：** get_db 给这个请求一个 AsyncSession，查询结束自动关闭。
4. **候选：** ReviewRecord 按当前用户和 next_review_at <= UTC now 过滤。
5. **关联：** JOIN Note 取标题、正文、标签和分类，再次用 Note.user_id 限定归属。
6. **投影：** 服务只取 200 字符预览，空 tags/category 标准化。
7. **响应：** ReviewTodayResponse 生成 reviews 与 total_count，success_response 编成 JSON。

**事务与隔离边界：** 列表读操作没有 commit；它不会改变回顾进度。用户隔离在 MySQL WHERE 中实现，不能依赖前端只展示自己数据。若读到历史无回顾行的笔记，本篇不会自动回填，因为读请求隐式写入会让分页、缓存和重试变得难解释。

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

**核对上一章字段确实能支持今日查询**：`./backend/app/models/review_record.py`。先看回顾卡上是否真的写着预约日期和归属。列表查询不应该从笔记正文推断到期日；它应直接比较 review_records.next_review_at，并用 note_id 找到笔记标题。字段缺失时不能在路由里临时拼字典掩盖模型问题。

可用的定位或请求片段：

```bash
rg -n "note_id|user_id|next_review_at|review_count|interval_days" backend/app/models/review_record.py
```

观察点：能找到需要的五个字段。 若不符合，如果文件不同于第 27 篇，先按实际模型调整教程，不要在查询里引用不存在的列。

**确认 JOIN 的笔记主键和归属列**：`./backend/app/models/note.py`。JOIN 就像把两张登记表用同一张书的编号扣在一起。只用 ReviewRecord.note_id=Note.id 还不够；每张表都应限定当前 user_id，以防历史脏数据或错误写入把不属于该用户的笔记带出来。

可用的定位或请求片段：

```bash
rg -n "__tablename__|id =|user_id =|title =|content =|tags =|category =" backend/app/models/note.py
```

观察点：确认 Notes 与 ReviewRecord 都有 user_id，可分别过滤。 若不符合，若两张表 user_id 设计不一致，先解决数据迁移和约束，而不是在前端做筛选。

**确认查询时钟与创建记录时同为 UTC**：`./backend/app/services/review_schedule.py`。一次“今天”的判断只在相同时间坐标下才有意义。第 27 篇写入 next_review_at 使用 UTC-naive，本篇比较也用同一函数；若新查询改成主机本地时间，数据库里的预约可能提前或推迟数小时。此命令不改数据，但能快速发现时钟函数导入错误。

可用的定位或请求片段：

```bash
uv run python -c "from app.services.review_schedule import utc_naive_now; print(utc_naive_now().isoformat())"
```

观察点：打印一个没有时区后缀的 UTC 时间；与系统 UTC 近似。 若不符合，若打印本地时间或时区对象，先统一时间约定，再验收到期筛选。

**核对编译与路由导入**：`./backend/main.py`。语法和导入是两种检查：compileall 确认源文件能解析，导入 main:app 才会解析路由依赖与 Pydantic 模型。两者都应在真实 HTTP 前完成；编译通过不意味着账号隔离正确，后面的双账号请求继续检验数据边界。

可用的定位或请求片段：

```bash
uv run python -m compileall -q app main.py
```

观察点：无编译异常，随后导入 main 可读到 review_router。 若不符合，若模块循环导入，检查模型、service、router 的单向依赖，而不是在路由中反向引用 main。

**用有效令牌读取空或非空结果**：`./backend/app/router/review_router.py`。先用已有用户看响应形状：空的 `reviews: []`、`total_count: 0` 是真实结果，不代表接口无效。若确有到期记录，检查标题和预览来自正确的 Note。这个步骤只读，重复访问不应推进计数或改变 next_review_at。

可用的定位或请求片段：

```bash
curl -sS http://127.0.0.1:8100/review/today -H "Authorization: Bearer $RAG_TOKEN" | python3 -m json.tool
```

观察点：HTTP 200，code=200，data 同时有 reviews 和 total_count。 若不符合，401 查 token；500 看 JOIN 字段和数据库表；空列表先查到期日期。

**检查用户隔离与到期边界**：`./backend/app/services/review_service.py`。用 MySQL 只读查询核对候选行，随后用另一个练习账号的 token 调接口。数据库里有候选行不等于“今天到期”，比较条件仍要成立。跨账号响应不能透出另一账号的标题、内容预览或总数。读表时尽量过滤临时账号，避免在终端输出其他真实用户数据。

可用的定位或请求片段：

```sql
SELECT user_id,note_id,next_review_at FROM review_records WHERE user_id="<本机测试用户ID>" ORDER BY next_review_at;
```

观察点：本账号只见到期行，另一个账号不见这些行。 若不符合，若跨账号泄露，立即检查 Note.user_id 与 ReviewRecord.user_id 是否都进 WHERE。

### 验收 1：检查路由注册

**准备与操作：** 重载后查询 OpenAPI。

```bash
curl -sS http://127.0.0.1:8100/openapi.json | python3 -c "import json,sys; print('/review/today' in json.load(sys.stdin)['paths'])"
```

**期望结果：** 输出 True。

**为什么要验这一项：** 排除忘记在 main.py include_router。

**不符合时从哪里查：** False 时看导入及服务重载日志。

### 验收 2：未登录访问

**准备与操作：** 不带 Authorization 头。

```bash
curl -i http://127.0.0.1:8100/review/today
```

**期望结果：** 返回 401。

**为什么要验这一项：** 查询涉及个人笔记，不允许匿名读取。

**不符合时从哪里查：** 若得到 200，检查 get_current_user_id 是否仍在签名中。

### 验收 3：新建笔记后暂不出现

**准备与操作：** 创建临时笔记后马上查 today。

```text
GET /review/today
```

**期望结果：** 记录初始次日到期，所以今天列表不应因新建而增加。

**为什么要验这一项：** 证明比较的是预约时间，不是“所有笔记”。

**不符合时从哪里查：** 若马上出现，检查初始 due_at 是否错误。

### 验收 4：把一条测试记录设为到期

**准备与操作：** 仅对专用临时笔记，通过 SQL 将 next_review_at 更新到 UTC_TIMESTAMP() 之前。

```sql
UPDATE review_records SET next_review_at=UTC_TIMESTAMP() - INTERVAL 1 MINUTE WHERE note_id="<临时ID>";
```

**期望结果：** 随后本账号列表出现该笔记。

**为什么要验这一项：** 用可控日期验证 <= 边界，不等明天。

**不符合时从哪里查：** 必须限定临时 ID，避免改动真实学习进度。

### 验收 5：核对列表字段

**准备与操作：** 查看刚才出现的对象。

```text
GET /review/today
```

**期望结果：** 有 review_id、note_id、title、preview、tags、category、count、last_reviewed_at、interval_days。

**为什么要验这一项：** 前端渲染依赖明确字段。

**不符合时从哪里查：** 字段缺失时查 ReviewItemResponse 构造。

### 验收 6：核对摘要长度

**准备与操作：** 测试笔记正文超过 200 字。

```text
GET /review/today
```

**期望结果：** content_preview 不超过 200 个 Python 字符。

**为什么要验这一项：** 避免列表下载全文。

**不符合时从哪里查：** 若超过，检查服务是否绕过切片表达式。

### 验收 7：验证稳定排序

**准备与操作：** 准备两条相同到期秒的临时记录。

```text
GET /review/today twice
```

**期望结果：** 两次顺序相同，按 next_review_at、id 排列。

**为什么要验这一项：** 没有第二排序键会使同秒记录顺序不稳定。

**不符合时从哪里查：** 检查 order_by 的两个字段。

### 验收 8：另一个用户看不到

**准备与操作：** 换账号令牌请求。

```text
GET /review/today
```

**期望结果：** 另一账号不出现本账号标题，总数也不包含本账号行。

**为什么要验这一项：** 用户隔离必须覆盖内容与统计。

**不符合时从哪里查：** 检查两个 user_id 过滤条件。

### 验收 9：重复读取不推进次数

**准备与操作：** 连读两次，查数据库。

```sql
SELECT review_count,next_review_at FROM review_records WHERE note_id="<临时ID>";
```

**期望结果：** 两个字段不变。

**为什么要验这一项：** 读接口不应成为写操作。

**不符合时从哪里查：** 若变化，查是否错误调用 mark_done。

### 验收 10：恢复并清理临时数据

**准备与操作：** 删除专用测试笔记。

```text
DELETE /note/<临时ID>
```

**期望结果：** 回顾行随外键级联消失，其他用户数据不变。

**为什么要验这一项：** 验收不留下干扰下一章的到期记录。

**不符合时从哪里查：** 若删除失败，检查账号归属和外键。

## 6. 深入动手与状态核对

### 从一条回顾行走到页面卡片

先准备一篇只属于账号 A 的临时笔记和它的回顾行。新建后它默认明天到期，所以立刻请求 `/review/today` 得到空列表是正确行为；若要验证正向列表，应只在临时记录上把 `next_review_at` 改成当前 UTC 之前，再请求一次。此时查询不是只读一张表：回顾行提供到期时间、完成次数和间隔，Note 提供标题、正文、标签与分类。`JOIN` 的连接条件是 `ReviewRecord.note_id == Note.id`；两个 `user_id` 条件把两张表都约束在当前令牌用户之内。只在路由里检查 JWT、却在 SQL 里漏了用户条件，仍可能返回他人资料。

服务取回 `(ReviewRecord, Note)` 成对行，再构造 `ReviewItemResponse`。前端要用 `note_id` 进入笔记和完成回顾，用 `review_id` 辨认回顾行，两者不能混。`content_preview` 最多 200 个字符，避免列表页把十篇长笔记的全部正文搬到浏览器；这不是对数据库正文的修改。早期笔记的 `tags` 或 `category` 可能是 NULL，因此转换成空列表和空字符串时只改 API 视图，不执行 UPDATE。这样前端看到稳定类型，数据库历史记录仍保持原样。

空列表测试要同时核对 `reviews=[]` 和 `total_count=0`。这里 `total_count` 计算的是本次实际返回的到期项目数；若未来加入分页，不能再拿当前页长度代替全部到期数。当前没有分页，记录很多时会一次取完全部到期行，生产环境应加 limit/offset 或游标，并为 `user_id,next_review_at` 的查询模式评估索引。性能问题不要凭直觉判断；先用测试数据和 `EXPLAIN` 看执行计划。第 27 篇模型只给两个单列索引，数据量增长后复合索引的收益要在真实查询下评估。

### 双账号与只读性质如何验收

让账号 A、B 各有一篇标题完全一样、正文含同样关键词的临时笔记，并把两条回顾记录都调成到期。A 的令牌调用接口时，响应只能有 A 的 `note_id`；B 同理。只看标题无法发现串号，因此要事先分别保存两篇笔记的 ID，再对照返回 ID。为了证明这个路由只读，记下 A 的 `review_count` 与 `next_review_at`，连续请求两次列表后重新读取数据库，这两个值应不变。回顾页刷新不该替用户自动完成学习任务，也不该顺手延后下次提醒。

如果请求返回 200 但列表仍空，按顺序检查：回顾行是否存在；`next_review_at` 是否确实不晚于 UTC 当前时刻；两张表的 `user_id` 是否与令牌一致；`note_id` 是否能 JOIN 到 Note；Uvicorn 是否连的是复刻数据库。不要先删除过滤条件“试试看”，那会把权限问题变成隐私泄露。若列表包含不属于当前用户的 ID，应立即停用接口并检查 SQL 条件和测试库数据，不能在前端通过过滤藏掉。

### 对照前端时逐字段判断，而不是只看 HTTP 200

复制来的回顾页面需要的是 `data.reviews`，不是裸列表；列表每项中的 `note_id` 会被用于完成操作和题目请求。若后端仅返回 `review_id`，页面可能渲染出卡片，但点击之后传错 ID，得到业务 404。`title` 与 `content_preview` 来自 Note，`review_count` 与 `interval_days` 来自 ReviewRecord。这个来源分工能在服务构造 Pydantic 对象时明确体现。响应 `data.total_count` 与本页 `reviews` 长度当前必须相同；不要用 notes 全部数量填这里，导致页面显示“10 项”却只有一项到期。

时钟条件 `next_review_at <= utc_naive_now()` 包含正好到期的边界。用 `<` 会在恰好相等的瞬间漏掉一条；虽通常只有极短时间差，这仍反映业务定义。排序先按最早到期，再按回顾行 ID，让重复请求得到稳定顺序。若只按到期时间，两条记录恰好同一秒时数据库可以交换它们的位置，前端卡片顺序可能抖动。查询时取一次当前时间作为参数更便于测试固定边界；当前示例在构造 SQL 时调用一次时钟，仍可确定本次查询的比较值。

注意 `JOIN` 默认内连接：若历史数据里有孤儿回顾行，列表不会返回它。正确的数据库外键本应阻止孤儿行，但旧表或关闭约束的导入可能留下脏数据。不要为了“让数量对上”改成不加约束的外连接并填一个假标题；应先按专用查询识别异常数据，决定迁移或修复。API 给用户的结果只应包含确实能打开的 Note。

若未来需要大量待回顾记录，不能简单把 `len(reviews)` 叫总数，同时在 SQL 里加 `limit 20`。分页必须另做相同过滤条件的 COUNT，并在排序后切页；两个查询之间数据也可能变化，页面要能容忍轻微差异。当前篇章没有分页，所以验收时只要核对全部到期记录与 `total_count` 即可。增加索引前先测 `WHERE user_id = ? AND next_review_at <= ? ORDER BY next_review_at` 的执行计划，别凭字段名猜索引是否被使用。

### 两次读取证明读接口没有副作用

准备当前用户一条到期临时记录，先用数据库读 `review_count`、`last_reviewed_at`、`next_review_at`，把这三个值写在本地练习记录里。连续请求 `/review/today` 两次，各自保存响应中该 note_id 的字段，再读数据库。三次观察应一致：列表顺序与字段相同，数据库进度完全不变。若列表第一次出现、第二次消失，说明某处把“领取今日任务”错当成“完成任务”；应该寻找隐含 UPDATE/commit，而不是给前端加缓存绕过。

为双账号隔离测试准备 A、B 两条同名到期笔记，分别保存两人的 token 和 note_id。先用 A 请求，确认响应 ID 集合只含 A 的专用 ID，再用 B 请求做镜像。不能简单断言“列表长度都是一”，因为账号可能已有其他到期笔记；应断言 A 的结果不含 B 的 ID，B 的结果不含 A 的 ID，并可在专用测试账号中明确控制样本总量。若响应里有别人的标题，即使点击详情仍被 404 拦住，列表接口也已泄露资料。修正点在 service 的 SQL，不在 React 组件里过滤。

还要检查空结果：用一个没有到期临时记录的新账号，GET 应返回 HTTP 200，业务 code 成功，`reviews=[]` 与 `total_count=0`。空结果不是 404，也不是数据库故障。断开 MySQL 再请求应是基础设施错误，不该吞异常转成空列表；否则用户无法区分“今天不需要复习”和“系统没查到”。做断库演练只针对复刻容器，并在结束后恢复服务，避免影响参考项目。

### 把三个“空”分开

新建的笔记尚未到期，所以当前用户的 today 列表为空；这是时间过滤的预期结果。历史笔记没有回顾行，也会为空；这是第 27 篇尚未执行回填的范围限制。MySQL 故障时查询无法执行，不能返回相同的空列表；应保留错误信号。为区分前两者，用笔记 ID 查回顾表：有行但 next_review_at 在未来，说明尚未到期；没有行，说明可能是旧笔记、创建事务没走到回顾逻辑或连错数据库。检查完再决定是等到期、为专用测试行调整日期，还是处理历史数据。

前端的今日卡片通常会展示内容预览与标签。服务层的 `content_preview=(note.content or "")[:200]` 只改变本次响应大小，数据库全文仍保留。`tags=note.tags or []` 解决旧记录可能为 NULL 的展示类型，不能由此推断数据库已经迁移为非空 JSON。要检查真实数据质量，应单独查询旧记录，并确定是否需要迁移；不要因 API 看起来正常就宣称库中字段一致。

如果到期项目很多，请求耗时可能来自 MySQL 查询、ORM 行构造或 JSON 响应体。先记录返回条数、响应大小、数据库执行时间，再决定加复合索引还是分页。当前没有分页时，`total_count` 是列表实际大小；引入分页后还要另查总数。这个扩展点与今日列表的定义直接有关，不需要提前引入 Redis 缓存。缓存若缺少用户维度或到期时间失效规则，反而可能显示过期或别人的回顾卡。

## 7. 工程面试思考

回答时要指向本篇具体文件、数据库约束或接口结果，区分当前已实现、验证时才可能观察到的结果与未来扩展。这里讨论设计判断，不背诵通用定义。

**面试官：为什么 JOIN 时还要过滤 Note.user_id？**

ReviewRecord.user_id 是当前回顾行的归属，但历史导入或代码错误可能把另一个用户的 note_id 填进来。双表都限定用户使查询即使遇到脏关联也不暴露标题与正文。外键只保证 note_id 存在，并不保证两个 user_id 一致。

**面试官：为什么列表请求不顺便补齐旧笔记的回顾记录？**

GET 应是可安全重复的读取；如果访问页面就批量写数据库，客户端重试、缓存或爬虫都可能触发不可见副作用。历史数据回填应有单独、可审计且幂等的迁移步骤。

**面试官：数据很多时这条查询哪里会慢？**

筛选条件是 user_id 和 next_review_at，JOIN 使用 note_id。当前教学数据量可先正确实现；增长后用 EXPLAIN 验证复合索引、限制返回条数并分页，不应先凭直觉添加索引，也不能在生产已有表上期待 create_all 自动加索引。

**面试官：什么叫“今天待回顾”？**

本篇定义为 next_review_at <= 当前 UTC 时刻，是一个“已到期”集合，而不是当地日历日。若产品要求按用户当地日历日展示，需要保存用户时区、在请求边界计算当天窗口，再用 UTC 范围查询。

## 8. 常见故障的定位顺序

- **只有空列表：** 核对 review_records 是否存在、next_review_at 是否到期、user_id 是否一致。
- **返回别人的标题：** 检查 JOIN 后 Note.user_id 条件，不能只过滤 ReviewRecord。
- **字段为 null：** 响应模型对 tags/category 做归一化，last_reviewed_at 允许 None。
- **接口 404：** main.py 未登记 review_router 或运行的是旧进程。
- **时间不对：** 与第 27 篇统一 UTC-naive；MySQL 会话时区另行核对。

## 9. 本篇边界和下一篇

本篇让回顾页能看见今日到期的真实笔记，但点击“完成回顾”还没有后端写入口。第 29 篇增加有并发保护的完成操作和下一次间隔计算。

本篇没有修改前端文件。新代码完成并经过你本机的验证后，才把它记为你亲手完成；仅阅读教程、助手先前的隔离检查或接口文档出现新路径，都不能代替真实执行。
