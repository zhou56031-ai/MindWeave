# 第 31 篇：用 DeepSeek 生成可校验的回顾选择题

> 前置：第 30 篇完成后的复刻后端。本文是待操作教程，写作时对照了正式复刻目录和参考项目；文中的预期结果不是正式工程已实测的结果。
> 成果：GET /review/question/{note_id} 在验证笔记归属后生成四选一题目，并严格检查 DeepSeek 的 JSON 结果。
> 范围：只指导后端；前端继续直接使用已经复制的源码。新增文件给完整代码，修改文件只给本次 diff，不重复整份最终源码。

## 1. 本篇要接通的真实能力

回顾页会按 note_id 请求一道问题。模型擅长生成自然语言，但数据库和前端需要稳定结构：question 是题干，choices 是四个互不重复的选项，answer 必须是其中一个。第 30 篇只保证得到非空文字，本篇把业务要求写成 Pydantic 规则。先按用户查笔记，再把有限长度正文送模型；不要先调用模型、最后才发现该用户根本无权看这篇笔记。

本篇从复刻项目现有代码继续，路径和导入均从下面这个固定目录算起。不要在参考仓库执行修改；那份源码用于比较接口与数据流。代码注释中【新增】标出本步新行为，diff 的正负号只用于定位，不要粘进 Python 文件。涉及账号或模型密钥时只用本机 `.env`，不把真实值写进教程或 Git。

**复刻根目录：**

```text
.
```

**本篇接口或产物契约：**

- `GET /review/question/{note_id}` 需要当前用户 JWT；他人或不存在的笔记都返回 404。
- 成功时 `data={question,choices,answer}`；choices 恰好四项、互不重复，answer 属于 choices。
- 模型输出虽请求 JSON 模式，仍由 json.loads 与 Pydantic 双层检查；不合格结果返回 502，不伪造“正确答案”。
- 输入正文截取上限，避免把整本长笔记无界发送给模型；密钥仍只留在后端。

**本篇与参考实现的差异：** 参考服务在模型失败时返回一组固定“自评”选项；本篇不把固定选项伪装成根据笔记生成的题。失败明确报告，前端可让用户重试。

**技术路线阅读：** 模型接口与同类路线看 [Q15](technology-routes/Q15-deepseek-model-client.md)；结构化输出约束依据 [DeepSeek JSON Output 官方说明](https://api-docs.deepseek.com/guides/json_mode/)。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 路径 | 本步职责 |
|---:|---|---|---|
| 1 | 【创建目录】 | `backend/app/prompt` | 建立提示词目录 |
| 2 | 【新增文件】 | `backend/app/prompt/review_question.txt` | 单独保存题目生成约束与 JSON 例子 |
| 3 | 【修改】 | `backend/app/schemas/models.py` | 声明题目输出的强约束 |
| 4 | 【修改】 | `backend/app/services/review_service.py` | 按用户查笔记、调用模型并校验答案 |
| 5 | 【修改】 | `backend/app/router/review_router.py` | 暴露前端正在调用的 question 路径 |

先看清楚上表：新文件的父目录若已存在就复用；步骤之间的 import 按顺序出现。每做完一个文件就做该步的小检查，不要把所有代码贴完才第一次启动。修改已有文件时请按 diff 的上下文搜索函数名或配置项，行号只供参考，因为上一章或你自己的改动可能改变行号。

## 3. 按顺序修改文件与验证

### 步骤 1：【创建目录】 `backend/app/prompt`

**文件职责：** 建立提示词目录

**执行位置或核验目标的完整地址：**

```text
./backend/app/prompt
```

**执行命令：**

```bash
mkdir -p backend/app/prompt
```

**整体解释：** 提示词文件先有固定的家：单独目录让题目文案与服务实现分开；重复执行 mkdir -p 不会删掉现有内容。

**工程位置与触发时刻：** 在复刻 backend 目录执行，下一步才创建 UTF-8 文本文件。

**完成这一小步的判断：** 目录存在，且现有文件未受影响。

**如果这里失败：** 若命令写进参考仓库，先回到复刻 backend 再执行。

### 步骤 2：【新增文件】 `backend/app/prompt/review_question.txt`

**文件职责：** 单独保存题目生成约束与 JSON 例子

**编辑文件的完整地址：**

```text
./backend/app/prompt/review_question.txt
```

**完整文件内容：**

```text
你是一位认真出题的学习教练。根据用户笔记生成一道四选一回顾题。
只输出 JSON 对象，不要 Markdown 围栏或额外说明。
JSON 字段固定为 question、choices、answer；choices 必须是四个互不相同的字符串；answer 必须与其中一个选项完全相同。
问题应检验笔记中的一个事实或关系；干扰项应合理，但不得把无法从笔记判断的内容写成正确答案。
示例 JSON：{"question":"笔记中提到的主要概念是什么？","choices":["概念A","概念B","概念C","概念D"],"answer":"概念A"}
用户笔记正文由单独的 user 消息提供。
```

**整体解释：** 提示词是给模型的任务单，不是给数据库或前端的规则。它明确写 JSON、字段名和四个选项，与第 30 篇的 JSON 模式配套；但模型仍可能不遵守，所以第 3 步用 Pydantic 复核。把提示词放在单独文件使修改文案时不必翻服务代码，也避免把用户笔记内容拼进系统提示。

**工程位置与触发时刻：** 服务每次生成题目前读取此文件；文件保存本身不会调用模型。

**完成这一小步的判断：** 文件是 UTF-8，包含 JSON 示例和不能输出围栏的指令。

**如果这里失败：** 若读取路径受终端当前目录影响，改用 __file__ 计算 prompt 目录。

### 步骤 3：【修改】 `backend/app/schemas/models.py`

**文件职责：** 声明题目输出的强约束

**编辑文件的完整地址：**

```text
./backend/app/schemas/models.py
```

**修改定位与前后对照：** 搜索代码块中的原函数或配置项，按 `-` 删除旧行、按 `+` 增加新行。只展示本篇变更。

```diff
@@
 class ReviewDoneResponse(BaseModel):
@@
     next_review_at: datetime
+
+
+class ReviewQuestionResponse(BaseModel):
+    question: str = Field(min_length=5, max_length=500)
+    choices: list[str] = Field(min_length=4, max_length=4)
+    answer: str
+
+    @model_validator(mode="after")
+    def check_options(self):
+        cleaned = [choice.strip() for choice in self.choices]
+        if any(not choice for choice in cleaned) or len(set(cleaned)) != 4:
+            raise ValueError("选项必须是四个不同的非空字符串")
+        if self.answer not in cleaned:
+            raise ValueError("答案必须来自选项")
+        self.choices = cleaned
+        return self
```

**整体解释：** 模型输出不能因为是合法 JSON 就当成合法选择题：`{"choices":[]}` 是合法 JSON，却无法在前端作答。这个响应模型像试卷验收员，检查题干长度、四个选项非空且不重复、答案能在选项里找到。它在服务解析模型输出后运行，失败由服务转成 502；不能把 Pydantic 栈追踪直接给浏览器。

**工程位置与触发时刻：** Pydantic 在 ReviewQuestionResponse.model_validate 时校验字段；导入模型不会执行验证。

**完成这一小步的判断：** 四选一合法数据通过；重复选项或答案不在选项中被拒绝。

**如果这里失败：** 如果 answer 两侧有空格导致失败，应在规则中明确归一化，而不是悄悄猜测正确答案。

### 步骤 4：【修改】 `backend/app/services/review_service.py`

**文件职责：** 按用户查笔记、调用模型并校验答案

**编辑文件的完整地址：**

```text
./backend/app/services/review_service.py
```

**修改定位与前后对照：** 搜索代码块中的原函数或配置项，按 `-` 删除旧行、按 `+` 增加新行。只展示本篇变更。

```diff
@@
+import json
+from pathlib import Path
+
+from fastapi import HTTPException
+from pydantic import ValidationError
@@
-from app.schemas.models import ReviewDoneResponse, ReviewItemResponse, ReviewTodayResponse
+from app.schemas.models import ReviewDoneResponse, ReviewItemResponse, ReviewQuestionResponse, ReviewTodayResponse
+from app.services.deepseek_client import deepseek_client
@@ class ReviewService:
+    async def question(
+        self, db: AsyncSession, user_id: str, note_id: str
+    ) -> ReviewQuestionResponse:
+        note = await db.scalar(select(Note).where(
+            Note.id == note_id, Note.user_id == user_id
+        ))
+        if note is None:
+            raise HTTPException(status_code=404, detail="笔记不存在")
+        prompt_path = Path(__file__).resolve().parents[1] / "prompt" / "review_question.txt"
+        system_prompt = prompt_path.read_text(encoding="utf-8")
+        raw = await deepseek_client.chat([
+            {"role": "system", "content": system_prompt},
+            {"role": "user", "content": (note.content or note.title)[:2000]},
+        ], json_mode=True, max_tokens=600)
+        try:
+            return ReviewQuestionResponse.model_validate(json.loads(raw))
+        except (ValueError, ValidationError) as exc:
+            raise HTTPException(status_code=502, detail="模型生成的题目不符合要求") from exc
```

**整体解释：** 服务先做授权查询，再读独立提示词，最后把有限长度笔记内容作为 user 消息交给 DeepSeek。模型像出题员，Pydantic 像阅卷前的排版检查：出题员交上 JSON 也不能跳过检查。若上游超时，第 30 篇客户端给 503；若输出格式不合格，这一层给 502。它不把模型原始文本、用户笔记正文或密钥写进异常消息。

**工程位置与触发时刻：** 只有有效用户访问自己的 note_id 才能触发外部付费请求；查无此笔记立即 404。

**完成这一小步的判断：** 合法模型 JSON 得到正确结构；无权限 ID 不调用模型。

**如果这里失败：** 若 prompt 路径找不到，检查服务文件 __file__ 的 parents[1] 是否为 app；不要依赖终端 cwd。

### 步骤 5：【修改】 `backend/app/router/review_router.py`

**文件职责：** 暴露前端正在调用的 question 路径

**编辑文件的完整地址：**

```text
./backend/app/router/review_router.py
```

**修改定位与前后对照：** 搜索代码块中的原函数或配置项，按 `-` 删除旧行、按 `+` 增加新行。只展示本篇变更。

```diff
@@
 @review_router.post("/done/{note_id}")
 async def mark_reviewed(
@@
     return success_response(message="已标记回顾", data=result)
+
+
+@review_router.get("/question/{note_id}")
+async def get_review_question(
+    note_id: str,
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> JSONResponse:
+    return success_response(data=await review_service.question(db, user_id, note_id))
```

**整体解释：** 前端传的是笔记 ID，不是回顾记录 ID；路由签名与路径保持一致。鉴权和数据库会话由 FastAPI 依赖注入，服务负责用户范围和模型调用。成功结果仍是统一 `{code,message,data}`，前端 reviewApi.getQuestion 会读取 data 并展示四个选项。

**工程位置与触发时刻：** 请求到了 /review/question/{note_id} 才调用 service.question；路由注册阶段不会产生模型费用。

**完成这一小步的判断：** OpenAPI 出现 GET 路径；他人 ID 返回 404。

**如果这里失败：** 如果前端显示空题，核对返回 data 的 question/choices/answer，而不是只看 HTTP 200。

## 4. 请求和状态如何穿过这些文件

下面只追踪本篇真正涉及的调用链，帮助把刚改的文件连起来；这段解释不需要复制进源码。

1. **前端：** DailyReview 把当前 note_id 交给 GET /review/question/{note_id}。
2. **身份：** JWT 依赖给出用户 ID。
3. **权限：** 服务在 Note 表里用 note_id+user_id 找到正文。
4. **提示：** 从 app/prompt/review_question.txt 读取固定业务要求，正文截断到 2000 字符。
5. **模型：** DeepSeekClient 以 JSON 模式请求 Chat Completions，处理超时和空内容。
6. **结构：** json.loads 得到对象，ReviewQuestionResponse 再检查四选一语义。
7. **响应：** 路由只把合格的 question/choices/answer 放进 data。

**事务与隔离边界：** 题目生成是按请求实时调用，当前没有缓存；刷新或重复点可能产生费用并得到不同题目。模型返回“格式正确”不等于题目事实一定正确，学习产品仍需要用户反馈、来源展示或人工评估。此接口只对当前用户的一篇笔记生成问题，不向模型发送全部知识库。

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

**确认已有今日列表与完成路由的位置**：`./backend/app/router/review_router.py`。当前回顾路由已经承接 /today 与 /done/{note_id}。新题目是固定前缀 `/question/{note_id}`，不会与已有路径冲突。先查看这个包如何引入鉴权与 get_db，让新增路由沿同一用户范围，而不是另建一个匿名 AI 接口。

可用的定位或请求片段：

```bash
rg -n "@review_router|async def" backend/app/router/review_router.py
```

观察点：看到 get_current_user_id 与两条已有路由。 若不符合，若你看见的是参考项目异步初始化版本，以正式复刻目录为准。

**核对 JSON 模式和超时处理**：`./backend/app/services/deepseek_client.py`。这一章的服务依赖第 30 篇的客户端。读一遍确认 `json_mode=True` 会传 response_format，网络故障会有限时间返回错误。如果服务直接在自己的代码里又拼一遍 API URL，就破坏了“统一调用边界”，后续补全和聊天会继续复制错误。

可用的定位或请求片段：

```bash
rg -n "response_format|Timeout|raise_for_status|choices" backend/app/services/deepseek_client.py
```

观察点：能找到 JSON 模式与内容提取逻辑。 若不符合，若客户端没有 json_mode 参数，先完成第 30 篇，不要在题目服务里自行发 HTTP。

**用纯 Python 数据检查题目约束**：`./backend/app/schemas/models.py`。不用先烧模型调用额度，也能证明 schema 至少对合法数据工作；再给重复选项或错误答案，确认它拒绝。纯验证不检查模型生成质量，但能把结构契约固定下来。这个阶段若失败，优先修 schema；真实 API 请求失败时才查 prompt 或 DeepSeek。

可用的定位或请求片段：

```bash
uv run python -c "from app.schemas.models import ReviewQuestionResponse; print(ReviewQuestionResponse(question='笔记的核心术语是什么？', choices=['A','B','C','D'], answer='A').model_dump())"
```

观察点：合法题通过，非法题抛 ValidationError。 若不符合，若模型返回的合法内容也过不了，检查题干最小长度与选项清理规则。

**先用他人或随机 ID 验证不会调用模型**：`./backend/app/router/review_router.py`。这是权限与成本检查：错误 ID 应在数据库 SELECT 后立即结束为 404；如果它仍去调外部模型，会产生不必要的延迟和费用，也可能把不该看见的正文送出。当前接口不允许把笔记正文放在 URL 或请求体里绕过归属判断。

可用的定位或请求片段：

```bash
curl -i http://127.0.0.1:8100/review/question/not-a-real-id -H "Authorization: Bearer $RAG_TOKEN"
```

观察点：HTTP 404，模型假服务或监控里没有新请求。 若不符合，如果模型仍被调用，调整服务顺序：先授权查 Note，再调用 deepseek_client。

**用专用临时笔记做一次真实生成**：`./backend/app/router/review_router.py`。在本机确认密钥已配置后，用不含秘密的短笔记请求一次。观察结构与答案归属，而不是要求题目文字每次完全相同；模型生成是非确定性的。验证后删除临时笔记及回顾行。若不愿调用外部付费模型，可先用本地假上游返回固定 JSON 走完整 HTTP 链。

可用的定位或请求片段：

```text
GET /review/question/<临时笔记ID>
```

观察点：HTTP 200，data 有四个选项，answer 在其中；或明确 503/502。 若不符合，503 查密钥/网络；502 查原始上游结构或 schema，但不要把用户内容写日志。

### 验收 1：确认路由

**准备与操作：** 重载服务查看 OpenAPI。

```text
GET /openapi.json
```

**期望结果：** 包含 /review/question/{note_id}。

**为什么要验这一项：** 先排除路由遗漏。

**不符合时从哪里查：** 没有路径检查 main 与 review_router 导入。

### 验收 2：匿名请求

**准备与操作：** 不带 token。

```text
GET /review/question/<临时ID>
```

**期望结果：** 401。

**为什么要验这一项：** 保护私人笔记和模型费用。

**不符合时从哪里查：** 若 200，检查鉴权依赖。

### 验收 3：他人笔记

**准备与操作：** 账号 B 请求账号 A 的 note_id。

```text
GET /review/question/<A_NOTE_ID>
```

**期望结果：** 404，模型不被调用。

**为什么要验这一项：** 授权必须先于付费请求。

**不符合时从哪里查：** 检查 select(Note).where 的 user_id。

### 验收 4：无密钥

**准备与操作：** 不配置 DEEPSEEK_API_KEY，请求本人 ID。

```text
GET /review/question/<OWN_NOTE_ID>
```

**期望结果：** 503，不返回假题。

**为什么要验这一项：** 区分没有服务与模型生成失败。

**不符合时从哪里查：** 查根目录 .env 与进程环境。

### 验收 5：合法模型 JSON

**准备与操作：** 假上游返回四选一对象。

```json
{"choices":["A","B","C","D"],"answer":"A","question":"笔记中的概念是什么？"}
```

**期望结果：** HTTP 200 且前端可显示。

**为什么要验这一项：** 完整验证 prompt→模型→schema→路由。

**不符合时从哪里查：** 检查 data 是否多套了一层。

### 验收 6：重复选项

**准备与操作：** 假上游返回 A,A,C,D。

```json
{"choices":["A","A","C","D"],"answer":"A","question":"笔记中的概念是什么？"}
```

**期望结果：** 502。

**为什么要验这一项：** 模型可能给出语法合法但不可作答内容。

**不符合时从哪里查：** 看 Pydantic check_options。

### 验收 7：答案不在选项

**准备与操作：** 假上游 answer=E。

```json
{"choices":["A","B","C","D"],"answer":"E","question":"笔记中的概念是什么？"}
```

**期望结果：** 502。

**为什么要验这一项：** 防止前端永远判错。

**不符合时从哪里查：** 不要擅自把 E 替换为 A。

### 验收 8：无效 JSON

**准备与操作：** 假上游返回截断文本。

```text
{"question":
```

**期望结果：** 502。

**为什么要验这一项：** 输出 token 上限和网络故障都可能截断。

**不符合时从哪里查：** 查 max_tokens 与上游响应，不打印私密正文。

### 验收 9：重复请求

**准备与操作：** 同一笔记请求两次。

```text
GET /review/question/<OWN_NOTE_ID> twice
```

**期望结果：** 都满足结构，但题目文字可能不同。

**为什么要验这一项：** 识别非确定性和调用费用。

**不符合时从哪里查：** 若产品要固定题目，引入缓存及失效策略。

### 验收 10：清理

**准备与操作：** 删除本篇专用笔记。

```text
DELETE /note/<临时ID>
```

**期望结果：** 笔记与回顾记录清理。

**为什么要验这一项：** 不会留下练习数据。

**不符合时从哪里查：** 不要删除用户原有笔记。

## 6. 深入动手与状态核对

### 一道题从私人笔记到结构化响应

回顾页请求 `/review/question/{note_id}` 时，第一件事是用当前 JWT 用户 ID 查这篇 Note。`note_id` 是浏览器提供的定位线索，不是授权凭据。若没查到，直接 404，不能先把这个 ID 对应的全文送给 DeepSeek 再回 404；那会产生费用，也会泄露他人的学习资料给外部服务。查到后只取有限长度的标题与正文，交给模型作为用户数据。提示词文件是题目规则，但不应把笔记正文拼成系统规则的一部分；用户写在笔记里的“忽略限制”仍只是待处理材料。

拿到模型返回字符串后，先 `json.loads` 区分“不是 JSON”和“是 JSON 但不是题目”。例如缺少 `answer`、只有三个 `choices`、四个选项有重复、正确答案不在选项里，都是合法 JSON 可能出现的业务错误。`ReviewQuestionResponse` 才是最终判定：题干、选项数、唯一性、答案归属同时满足才返回 200。失败用 502 告诉前端“上游生成的内容不符合当前契约”，而不是随便挑第一个选项充当答案。这样用户不会被系统自信地教错。

### 提示词与校验各自能保证什么

提示词能告诉模型倾向生成什么，但模型可能忽略、被截断或输出围栏；JSON 模式增加语法约束，但仍无法替你验证事实是否在笔记里。Pydantic 只保证形状，不证明题干没有歧义，也不能判断正确答案是否真的与原文一致。若要升级质量，收集一组已知笔记和预期题目特性，让人审或额外评估过程检查“题目可由正文回答”。用户仍应能跳过或反馈错误题目；不要把一次通过 schema 的题目当永久正确的知识事实。

在验收里至少设置两账号：A 拥有临时笔记，B 传入 A 的 ID，B 应收到 404 且假上游调用计数保持零。A 正常调用时，让假上游分别返回一份合格四选一和几份不合格 JSON，比较 HTTP 状态和 `data` 字段。再次打开今日列表时，`review_count` 和 `next_review_at` 不应因为“生成了一道题”改变；题目生成和“完成回顾”是两个分开的业务动作。

### 对四选一结果做可以复现的坏样本检查

一个合格样本应有非空题干、长度恰好为四的 `choices`、四个互不重复的字符串，并且 `answer` 与其中一个选项完全相同。至少准备四种不合格假上游响应：一是纯文字或 Markdown 围栏，`json.loads` 失败；二是 JSON 对象但缺 `answer`，Pydantic 拒绝；三是四个选项中两个只差首尾空格，归一化后重复；四是答案看似相近但不在 choices 里。请求都应该得到 502，而不是返回部分数据或自动补一个选项。这样验证的是“模型输出被审查”，不是“提示词写得像要求模型守规矩”。

如果模型返回 `choices` 中含数字或对象，Pydantic 对 `list[str]` 的实际校验会阻止不符合预期的类型。题目长度边界也要验证：过短题干即使 JSON 结构完整，仍不能给用户一张“？”卡片。正确答案的比较应有明确归一化策略；当前示例只 strip 选项，不 strip answer，所以模型在答案两侧多空格会被拒绝。这是宁可报错也不暗猜的选择。若产品希望更宽容，应同时规范化 answer 并补测试，而不是只在某个路由里临时修字符串。

题目生成是读取笔记加一次外部计算，不修改回顾次数。用户打开一道题但没有答、模型失败或关闭页面，都不应变成“完成回顾”。第 29 篇 `/review/done/{note_id}` 是独立的写操作。这样的状态分离能避免用户只是预览题目却被系统安排下次复习。若前端点击“完成”发生在答案展示之后，后端仍要独立判断该记录到期且属于当前用户，不能因为前端说已经答对就绕开权限和时间条件。

提示词文件若将来变更，可以逐次比较同一组测试笔记的结构合格率和人工质量。因为模型不确定性，无法要求两个真实调用逐字相同；假上游负责确定性协议测试，真实模型小样本负责质量观察。无论何种测试都不要把其他用户正文写入日志。若出现 503，应先查密钥和网络；若 502，应看输出解析与 schema；这两种失败性质不同，不能在 UI 都显示“笔记不存在”。

### 确认“生成题目”与“完成回顾”从未串成同一动作

用临时到期笔记先请求今日列表，保存它当前的 `review_count` 与 `next_review_at`。请求题目接口，收到一份合法题目后再次读今日列表和数据库，这两个进度字段必须完全不变。即使前端显示了题目和选项，用户尚未点完成；若把 `/review/question/{note_id}` 设计成顺手推进，会让打开页面等于完成学习。之后单独 POST `/review/done/{note_id}` 才应改变状态。这里的顺序体现两类服务职责：模型服务生成可展示内容，回顾服务根据明确用户动作推进日程。

对权限的验收要观察上游调用次数。让 B 请求 A 笔记的题目，HTTP 404 且本地假 DeepSeek 服务零请求；如果最终也返回 404 但假上游已收到 A 的正文，仍然是失败，因为私人数据已经被送出。不存在的 note_id 和他人 note_id 可以返回相同的对外状态，避免枚举资源。A 的合法请求才允许进入模型调用，输入长度应受限，不能把十万字笔记全部发给外部服务。

对结构质量的验收不要只留一个“正常 JSON”样本。至少验证空 choices、重复选项、答案不在 choices、字段类型错误、被 Markdown 围栏包裹的 JSON，以及合法四选一。每次假上游输出都应有确定的 HTTP 状态；合格样本的数据形状与前端一致，不合格样本统一 502，不能把模型原文塞进错误 detail。若某个真实模型回复经常 502，先记录脱敏后的失败类型、调整提示或模型配置，再比较合格率，不能为了减少错误直接删除校验。

### 题目输入如何避免无界外发

Note 的 title 与 content 可能包含私人资料，服务只能在确认当前 user_id 拥有该 Note 后取得并发送有限正文。截断长度要在业务代码里明确可见，且在 prompt 中不要谎称模型读过未发送的部分。若只截取正文前 3000 字，主题藏在后半部分时题目可能失焦；这属于当前实现的质量边界。后续可先做本地摘要或按段选取，但每一步仍要保留用户授权与成本上限。不能让前端把任意 note_id 放进请求后由模型自己决定能否访问。

单次调用时，`DeepSeekClient.chat(..., json_mode=True)` 只表示希望输出 JSON 对象。模型仍可能返回合法 JSON 但内容空洞，或者返回了可解析的 JSON 字符串而非对象。`ReviewQuestionResponse.model_validate` 会拒绝不匹配的形状。若 schema 验证失败，服务应把错误映射为 502，且不要在业务响应里附上整段用户笔记或完整模型原文。服务端可以在脱敏日志里记录失败类型和模型请求 ID，便于修提示词，而不是记录真实内容。

若模型正常返回题目但用户立刻删除了那篇笔记，客户端之后点击完成应在服务端得到 404；题目响应不能赋予已经失效的永久操作权。外部模型调用和数据库状态不是同一事务，期间笔记也可能被修改。当前篇章没有版本快照，因此题目反映的是请求开始时读取到的那份正文；若要避免旧题对应新正文，应在请求中携带版本号并在完成操作前复核。这个场景说明“先鉴权再调模型”必要，但并不保证外部计算期间数据永远不变。

## 7. 工程面试思考

回答时要指向本篇具体文件、数据库约束或接口结果，区分当前已实现、验证时才可能观察到的结果与未来扩展。这里讨论设计判断，不背诵通用定义。

**面试官：为什么在生成题之前先查笔记归属？**

模型调用会处理正文并产生费用。若先调模型后鉴权，即使最终 HTTP 返回 404，也已把私密正文送到外部并消费额度。服务应先按 note_id+user_id 查询，失败立即结束。

**面试官：有 JSON 模式还需要 Pydantic 吗？**

JSON 模式只解决语法格式，不能保证 choices 恰好四个、答案属于选项、题干不是空话。业务 schema 是第二道门；失败清楚返回 502，而不是让前端勉强渲染。

**面试官：模型服务故障能否给用户一个固定题继续？**

可以作为明确标注的降级产品设计，但不能把固定自评题说成“根据该笔记生成”。当前阶段选择透明失败，便于发现配置和质量问题。未来可提供“改为自评模式”的显式选择。

**面试官：如何控制隐私、成本与滥用？**

限制正文长度、先鉴权、设置 max_tokens 和超时是第一层。生产还应加按用户限流、预算、结果缓存和审计；缓存键应包含用户、笔记内容版本和模型/提示词版本，避免旧题或跨用户串用。

## 8. 常见故障的定位顺序

- **总是 404：** 核对 note_id 是否是笔记 ID，而非 review_id。
- **503：** 区分未配置密钥、上游网络或配额。
- **502：** 区分 HTTP 响应形状错误与题目字段不合格。
- **题目总相同：** 检查是否误写死固定 JSON 或复用了过期缓存。
- **高费用：** 重复请求目前不缓存；后续按内容版本设计缓存。

## 9. 本篇边界和下一篇

回顾页现在能读取、完成并生成题目。第 32 篇把同一 DeepSeek 调用边界用于笔记编辑器的内联补全与写作辅助，但保持编辑操作由用户确认。

本篇没有修改前端文件。新代码完成并经过你本机的验证后，才把它记为你亲手完成；仅阅读教程、助手先前的隔离检查或接口文档出现新路径，都不能代替真实执行。
