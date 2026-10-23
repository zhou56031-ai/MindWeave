# 第 30 篇：统一 DeepSeek 配置、超时与模型调用边界

> 前置：第 29 篇完成后的复刻后端。本文是待操作教程，写作时对照了正式复刻目录和参考项目；文中的预期结果不是正式工程已实测的结果。
> 成果：后端有一个可复用的异步 DeepSeek Chat Completions 客户端；密钥只来自本机环境，失败转为明确状态。
> 范围：只指导后端；前端继续直接使用已经复制的源码。新增文件给完整代码，修改文件只给本次 diff，不重复整份最终源码。

## 1. 本篇要接通的真实能力

接下来回顾题、笔记补全和聊天都要调用同一个模型。如果每个路由自己拼 URL、密钥和异常处理，十几处代码会逐渐变成十几种行为。本篇先建立统一的 AI 出口：配置只从 settings 读取，httpx 的异步调用有明确超时，不把用户输入或密钥写进日志。DeepSeek 提供 OpenAI 兼容的 Chat Completions 接口；本篇只接文字输入与文字输出，图片、工具调用和推理模式留在后续阶段。官方当前示例使用 `https://api.deepseek.com/chat/completions` 与 `deepseek-flash`，版本会变化，因此模型名做成配置，不埋死在业务函数中。

本篇从复刻项目现有代码继续，路径和导入均从下面这个固定目录算起。不要在参考仓库执行修改；那份源码用于比较接口与数据流。代码注释中【新增】标出本步新行为，diff 的正负号只用于定位，不要粘进 Python 文件。涉及账号或模型密钥时只用本机 `.env`，不把真实值写进教程或 Git。

**复刻根目录：**

```text
.
```

**本篇接口或产物契约：**

- 应用只从 `.env` 或进程环境读取 `DEEPSEEK_API_KEY`，前端和教程都不出现真实值。
- `deepseek_client.chat(messages, json_mode=False, max_tokens=...)` 返回非空文本；JSON 模式另外要求提示中说明输出 JSON。
- 缺少密钥为 503；网络或上游失败对调用方表现为 503；上游返回非预期结构为 502。
- 连接、读取、写入、等待连接池都设置超时；业务层不直接操作 HTTP Authorization 头。

**本篇与参考实现的差异：** 参考项目通过 LangChain 模型封装复用 OpenAI 兼容配置；教学阶段先用 httpx 包装最小 Chat Completions HTTP 链路，让请求和异常边界更可见。第 36 篇会在这个边界上增加流式输出。

**技术路线阅读：** [Q15：DeepSeek Chat Completions、SDK 与本地模型的比较](technology-routes/Q15-deepseek-model-client.md)。接口事实以 [DeepSeek 官方入门](https://api-docs.deepseek.com/guides/search_fetch) 和 [HTTPX 超时文档](https://www.python-httpx.org/advanced/timeouts/) 为准。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 路径 | 本步职责 |
|---:|---|---|---|
| 1 | 【修改】 | `backend/app/core/settings.py` | 声明模型密钥、地址和可替换的模型名 |
| 2 | 【修改】 | `.env.example` | 公开变量名和安全占位符，不保存真实钥匙 |
| 3 | 【安装依赖】 | `backend/pyproject.toml` | 安装异步 HTTP 客户端并同步依赖文件 |
| 4 | 【同步依赖】 | `backend/requirements.txt` | 从 uv.lock 重导可复现依赖清单 |
| 5 | 【新增文件】 | `backend/app/services/deepseek_client.py` | 集中构造异步请求、校验响应和隐藏上游错误 |
| 6 | 【配置】 | `.env` | 将本机密钥加入被忽略的 .env |

先看清楚上表：新文件的父目录若已存在就复用；步骤之间的 import 按顺序出现。每做完一个文件就做该步的小检查，不要把所有代码贴完才第一次启动。修改已有文件时请按 diff 的上下文搜索函数名或配置项，行号只供参考，因为上一章或你自己的改动可能改变行号。

## 3. 按顺序修改文件与验证

### 步骤 1：【修改】 `backend/app/core/settings.py`

**文件职责：** 声明模型密钥、地址和可替换的模型名

**编辑文件的完整地址：**

```text
./backend/app/core/settings.py
```

**修改定位与前后对照：** 搜索代码块中的原函数或配置项，按 `-` 删除旧行、按 `+` 增加新行。只展示本篇变更。

```diff
@@ class Settings(BaseSettings):
     REDIS_DB: int = Field(default=3, ge=0)
+
+    # 【新增】模型密钥只在后端配置层读取；模型名可以随官方版本调整。
+    DEEPSEEK_API_KEY: SecretStr = SecretStr("")
+    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
+    DEEPSEEK_MODEL: str = "deepseek-flash"
```

**整体解释：** 配置中心像应用的钥匙柜。服务代码只索取 `settings.DEEPSEEK_API_KEY`，不会把钥匙写在源码里。SecretStr 的普通显示会遮蔽内容，但真正发 Authorization 头时必须显式 get_secret_value。BASE_URL 与 MODEL 也统一放这里：测试时可指向本机假服务，官方更换模型别名时只需改配置。默认空 key 让非 AI 功能仍可启动；真正调用 AI 时明确返回 503。

**工程位置与触发时刻：** settings 在进程导入时实例化；改变 .env 后需要重启或重载后端，不会自动热更新已创建对象。

**完成这一小步的判断：** 导入 settings 时可看到模型名和 base URL，打印 SecretStr 不显示原文。

**如果这里失败：** 若更新 .env 后仍提示缺 key，先查根目录位置和 Uvicorn 进程环境变量优先级。

### 步骤 2：【修改】 `.env.example`

**文件职责：** 公开变量名和安全占位符，不保存真实钥匙

**编辑文件的完整地址：**

```text
./.env.example
```

**修改定位与前后对照：** 搜索代码块中的原函数或配置项，按 `-` 删除旧行、按 `+` 增加新行。只展示本篇变更。

```diff
@@
 REDIS_DB=3
+DEEPSEEK_API_KEY=
+DEEPSEEK_BASE_URL=https://api.deepseek.com
+DEEPSEEK_MODEL=deepseek-flash
```

**整体解释：** `.env.example` 是一张空白申请表，用来告诉复刻者有哪些配置项；它不是私密保险柜。留空的 DEEPSEEK_API_KEY 使项目克隆后仍能启动与学习前 29 篇。真实值只能放本机已忽略的 `.env`，如果之前在对话里给过某个密钥，也不要复制到教程、Git 或前端。模型地址和名字是普通配置，可公开。

**工程位置与触发时刻：** Compose 不会用这几个变量；只有后端 settings 导入时读取，模型调用时才使用。

**完成这一小步的判断：** Git diff 只出现空白占位，真实 .env 仍被忽略。

**如果这里失败：** 若 Git status 出现 .env，本章先修复忽略规则，不要提交它。

### 步骤 3：【安装依赖】 `backend/pyproject.toml`

**文件职责：** 安装异步 HTTP 客户端并同步依赖文件

**执行位置或核验目标的完整地址：**

```text
./backend/pyproject.toml
```

**执行命令：**

```bash
uv add httpx
```

**整体解释：** httpx 提供 AsyncClient，使 FastAPI 的 async 路由等待外部模型时不阻塞事件循环。依赖必须由 uv 写入 pyproject.toml 与 uv.lock，再从锁文件导出 requirements.txt；不要手抄一个猜测版本。这里只新增一个直接依赖，其他现有包仍沿用锁定组合。

**工程位置与触发时刻：** 在复刻 backend 执行一次 uv add；项目文件变化发生在命令完成后。

**完成这一小步的判断：** pyproject.toml 有 httpx，uv.lock 解析成功。

**如果这里失败：** 若解析失败，看 Python 版本和网络；不要只往 requirements.txt 追加一行而跳过锁文件。

### 步骤 4：【同步依赖】 `backend/requirements.txt`

**文件职责：** 从 uv.lock 重导可复现依赖清单

**执行位置或核验目标的完整地址：**

```text
./backend/requirements.txt
```

**执行命令：**

```bash
uv export --locked --no-dev --no-emit-project --no-hashes --format requirements.txt --output-file requirements.txt
```

**整体解释：** 三个依赖文件扮演不同角色：pyproject.toml 说“我要什么”，uv.lock 写“这次实际解析到什么”，requirements.txt 是兼容其他安装方式的导出副本。本篇模型调用是否能运行取决于当前 .venv 中确实有 httpx，命令执行后再用 uv run 做导入检查。

**工程位置与触发时刻：** 导出命令不会请求 DeepSeek，也不会读取 API key。

**完成这一小步的判断：** requirements.txt 含 httpx 及其传递依赖，uv sync --locked --check 不要求改动。

**如果这里失败：** 若 --locked 报错，说明锁文件和项目声明不一致，先重新完成 uv add。

### 步骤 5：【新增文件】 `backend/app/services/deepseek_client.py`

**文件职责：** 集中构造异步请求、校验响应和隐藏上游错误

**编辑文件的完整地址：**

```text
./backend/app/services/deepseek_client.py
```

**完整文件内容：**

```python
"""DeepSeek 的文字 Chat Completions 边界。"""
from collections.abc import Sequence
from typing import Any
import httpx
from fastapi import HTTPException
from app.core.settings import settings

class DeepSeekClient:
    async def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        json_mode: bool = False,
        max_tokens: int = 512,
    ) -> str:
        key = settings.DEEPSEEK_API_KEY.get_secret_value()
        if not key:
            raise HTTPException(status_code=503, detail="模型服务未配置")
        if not messages or max_tokens < 1 or max_tokens > 4096:
            raise ValueError("模型消息或输出上限不合法")
        body: dict[str, Any] = {
            "model": settings.DEEPSEEK_MODEL,
            "messages": list(messages),
            "max_tokens": max_tokens,
            "stream": False,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        timeout = httpx.Timeout(30.0, connect=5.0, read=30.0, write=10.0, pool=5.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    settings.DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json=body,
                )
                response.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            raise HTTPException(status_code=503, detail="模型服务暂不可用") from exc
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=502, detail="模型响应格式异常") from exc
        if not isinstance(content, str) or not content.strip():
            raise HTTPException(status_code=502, detail="模型没有返回文字")
        return content.strip()

deepseek_client = DeepSeekClient()
```

**整体解释：** 这个文件是业务服务和外部模型之间的边界。可以把它看成翻译员：路由或回顾服务只交“角色+文字”消息；翻译员统一加模型名、密钥头、超时和 JSON 模式，再把上游复杂响应提取成一段非空文字。它不存数据库、不判断用户能否访问笔记，也不把原始上游异常详情回给浏览器。网络失败与内容格式错误分开报 503/502，方便判断是服务不可达还是接口契约变化。

**工程位置与触发时刻：** 后续 review_question、note_autocomplete 与 chat 流程调用 chat；导入文件时不会发送请求。

**完成这一小步的判断：** 没有 key 时立即 503；给本地假上游能验证 body、header 和文本提取。

**如果这里失败：** 若上游返回 401，不要在前端填密钥；核对本机 .env 是否正确、是否被环境变量覆盖，并避免打印密钥。

### 步骤 6：【配置】 `.env`

**文件职责：** 将本机密钥加入被忽略的 .env

**执行位置或核验目标的完整地址：**

```text
./.env
```

**本机配置内容（将占位密钥替换后保存）：**

```dotenv
DEEPSEEK_API_KEY=<在本机替换成你的真实密钥>
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
```

**整体解释：** 在复刻根目录的已有 .env 文件末尾加入这三项，并把尖括号整段替换为本机真实密钥；不要把占位文本当成可用密钥。文件不得提交、截图或贴进章节。测试可以用进程环境变量临时覆盖，正式环境应使用密钥管理。

**工程位置与触发时刻：** 修改 .env 后重启后端，Settings 下次导入时才读到新值。

**完成这一小步的判断：** 变量名存在，Git 不跟踪 .env，服务能得到非空 SecretStr。

**如果这里失败：** 若当前目录在 backend，`../.env` 才是复刻根目录文件；不要把密钥写进 backend/.env 后误以为会被读取。

## 4. 请求和状态如何穿过这些文件

下面只追踪本篇真正涉及的调用链，帮助把刚改的文件连起来；这段解释不需要复制进源码。

1. **调用方：** 回顾题、笔记补全或聊天服务组装 system/user 消息。
2. **配置：** DeepSeekClient 从 settings 取模型名、基础 URL、SecretStr 密钥。
3. **请求：** httpx AsyncClient 带超时与 Authorization 头发送 POST /chat/completions。
4. **上游：** DeepSeek 返回 choices[0].message.content，客户端提取非空文本。
5. **JSON 模式：** 调用方要求时带 response_format，但还必须在消息中要求 JSON，并在业务层用 schema 验证字段。
6. **错误：** 缺配置 503，网络/状态错误 503，异常响应结构 502；不把密钥或原始上游正文回传。
7. **关闭：** 本次 AsyncClient 通过 async with 关闭；后端事件循环继续服务其他请求。

**事务与隔离边界：** 这层只保证一个有界的 HTTP 模型调用，不保证回答正确、事实可追溯或用户输入安全。它不取代业务层的 Pydantic 校验、用户权限和来源引用。外部 API 和 MySQL 不是一个事务；若模型成功而数据库提交失败，业务必须显式决定重试还是丢弃模型结果。

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

**核对现有配置加载位置与 SecretStr 习惯**：`./backend/app/core/settings.py`。已有 JWT 密钥是 SecretStr 且由复刻根目录的 .env 读取，新模型密钥应沿同一条路径。不要在 service 里再读 `os.getenv`，否则本机 .env 的位置、测试覆盖方法和错误提示会分叉。先看真实配置，确定新增字段放在 Settings 类中。

可用的定位或请求片段：

```bash
rg -n "REBUILD_ROOT|env_file|SecretStr|SECRET_KEY" backend/app/core/settings.py
```

观察点：确认 REBUILD_ROOT 指向复刻根目录，.env 不在前端。 若不符合，若你进入的是参考仓库的 settings.py，就停止；两个项目的密钥和端口不能混用。

**验证无密钥的可控失败**：`./backend/app/services/deepseek_client.py`。编译可排除语法错误，但下一步还要做不含真实密钥的假上游测试。无密钥 503 是设计的失败模式：笔记和知识库仍能运行，只有调用 AI 的功能不可用。这比应用一启动就因没有模型账户而崩溃更适合循序复刻。

可用的定位或请求片段：

```bash
uv run python -m compileall -q app/services/deepseek_client.py
```

观察点：无语法错误；缺密钥调用抛可识别的 503。 若不符合，如果导入就发网络请求，检查是否把 await client.post 写在模块顶层。

**用本地假上游先校验请求格式**：`./backend/app/services/deepseek_client.py`。真实 DeepSeek 调用可能收费、受限流或受网络代理影响；先用本地假上游返回一个与官方结构相同的 JSON，可验证 Authorization 头存在、`model` 和 `messages` 正确、返回内容被提取。此检查不需要公开密钥。真实小请求只在你本机确认配置后手动执行一次，记录耗时、状态和模型名，不记录 prompt 中的私密内容。

可用的定位或请求片段：

```bash
uv run python -c "from app.services.deepseek_client import deepseek_client; print(type(deepseek_client).__name__)"
```

观察点：对象可导入；后续假上游测试能返回预置文字。 若不符合，若导入失败，看 uv sync、settings 导入和 SecretStr；若真实调用失败先区分 503 与 502。

**确认模型客户端不占用数据库启动路径**：`./backend/app/core/lifespan.py`。AI 是外部可选能力，MySQL/Redis 的健康检查不应该被 DeepSeek 网络状况拖住。本篇 DeepSeekClient 按请求创建短生命周期 AsyncClient，所以 lifespan 无需再打开持久连接；将来高并发时可改成共享连接池并在关闭阶段 aclose，但必须有配套生命周期管理。

可用的定位或请求片段：

```bash
rg -n "init_db|yield|dispose" backend/app/core/lifespan.py
```

观察点：没有因未配置 DeepSeek 而阻断 /health/ready。 若不符合，如果启动阶段开始等待模型，检查是否错误地在 lifespan 调用了 chat。

### 验收 1：检查依赖锁定

**准备与操作：** 在 backend 查看三个依赖文件。

```bash
uv sync --locked --check
```

**期望结果：** 不需要额外安装，httpx 可导入。

**为什么要验这一项：** 依赖可复现才值得继续调 API。

**不符合时从哪里查：** 失败时重新执行 uv add 与 uv export。

### 验收 2：缺密钥

**准备与操作：** 确保临时测试进程没有 DEEPSEEK_API_KEY，调用 chat。

```bash
uv run python -c "from app.core.settings import settings; print(bool(settings.DEEPSEEK_API_KEY.get_secret_value()))"
```

**期望结果：** 输出 False；真正调用时明确 503。

**为什么要验这一项：** 不允许空密钥请求发到外网。

**不符合时从哪里查：** 若输出 True，说明本机已有配置，不要在终端打印它。

### 验收 3：密钥不出现在日志

**准备与操作：** 以占位配置启动并搜索日志。

```bash
rg -n "Authorization|DEEPSEEK_API_KEY" backend/app/services/deepseek_client.py
```

**期望结果：** 源码只出现变量名，无原始值。

**为什么要验这一项：** 避免源码与日志泄露。

**不符合时从哪里查：** 检查异常处理是否回传上游原文。

### 验收 4：URL 组装

**准备与操作：** 将 BASE_URL 设为带或不带尾斜杠的假地址。

```text
POST /chat/completions
```

**期望结果：** 最终路径只有一个斜杠。

**为什么要验这一项：** 配置灵活但不重复斜杠。

**不符合时从哪里查：** 检查 rstrip("/")。

### 验收 5：正常响应解析

**准备与操作：** 假上游返回 choices[0].message.content。

```json
{"choices":[{"message":{"content":" 你好 "}}]}
```

**期望结果：** chat 返回“你好”。

**为什么要验这一项：** 验证客户端提取而非透传整份 JSON。

**不符合时从哪里查：** 若返回空，检查 content 类型和 strip。

### 验收 6：上游结构异常

**准备与操作：** 假上游返回空 choices。

```json
{"choices":[]}
```

**期望结果：** 客户端返回 502。

**为什么要验这一项：** API 协议变化应被识别。

**不符合时从哪里查：** 检查 response.json 的异常捕获。

### 验收 7：网络超时

**准备与操作：** 假上游延迟超过 read timeout。

```python
await deepseek_client.chat([...])
```

**期望结果：** 客户端有限时间内返回 503。

**为什么要验这一项：** 避免一个模型请求一直占用服务资源。

**不符合时从哪里查：** 区分 connect/read/pool 超时。

### 验收 8：JSON 模式

**准备与操作：** 用假上游记录请求体。

```python
await deepseek_client.chat([...], json_mode=True)
```

**期望结果：** 请求体含 response_format=json_object。

**为什么要验这一项：** 结构化任务需要协议开关。

**不符合时从哪里查：** 若上游无限空白，检查提示中是否明确写 JSON。

### 验收 9：真实小请求

**准备与操作：** 本机有有效密钥后，只发不含私人资料的短 prompt。

```bash
uv run python -c "# 按本篇服务方法发一条短消息；不要打印密钥"
```

**期望结果：** 返回非空文本或明确 503/502；记录状态与耗时。

**为什么要验这一项：** 验证实际网络、账户权限与当前模型名。

**不符合时从哪里查：** 不要把钥匙贴到 curl 命令历史里。

### 验收 10：基础功能仍可用

**准备与操作：** 暂时不配置模型，访问 ready 与笔记列表。

```text
GET /health/ready ; GET /note/list
```

**期望结果：** 基础服务正常，AI 调用单独失败。

**为什么要验这一项：** 实现故障隔离。

**不符合时从哪里查：** 若 /ready 依赖 DeepSeek，检查 lifespan 是否被误改。

## 6. 深入动手与状态核对

### 先把“能启动”和“能调模型”分开验证

应用启动的可靠性不能被外部模型状态绑住。`Settings` 读到一个空 `DEEPSEEK_API_KEY` 时，MySQL、Redis、笔记和知识库仍应正常启动；只有实际调用 `DeepSeekClient.chat` 才得到“未配置”的 503。这样在无密钥的学习环境里仍能完成前面的教程。若把探测 DeepSeek 放进 `lifespan`，上游波动可能让整个后端无法启动，与已有 `/ready` 对 MySQL/Redis 的语义混在一起。将来产品若要求 AI 可用性，可另设模型专用检查，不在此阶段假称基本就绪代表模型也就绪。

配置链要分清三处：`.env.example` 是公开模板，键值为空；复刻根目录 `.env` 是本机真实值，已被 Git 忽略；`Settings` 用 `SecretStr` 承载它，打印配置对象时不应露明文。终端里曾出现过真实密钥，也不意味着能把它写入教程或浏览器。浏览器只带用户 JWT 调你自己的 API。模型请求的 Authorization 头由后端统一生成，既不会从前端请求体读取，也不会回传给前端。修改 `.env` 后重启后端，让新进程重新装载配置；热更新 Python 文件不一定会重读环境文件。

### 假上游先于真实花费

写完客户端后，先把基础 URL 指向本机可控的假服务器，返回 `{"choices":[{"message":{"content":"你好"}}]}`。这时你能够在不花模型费用的情况下核对五件事：最终 URL 只有一个 `/chat/completions`；请求体带指定 `model` 和 `messages`；头里有 Bearer 但日志不打印值；`max_tokens` 有边界；返回被裁掉首尾空格后是 `你好`。再分别让假服务器返回空 choices、缺 content、HTTP 500、延迟超过 read timeout，客户端应给明确 502 或 503，不能把上游堆栈和密钥原样发给用户。

真实 DeepSeek 小请求只需用不含私人资料的短提示验证账户、模型名和网络。若 401，核对本机密钥、环境变量覆盖与上游账户权限；若 429，记录限流和重试等待，不要自动密集重发；若读超时，响应可能已经在上游生成，自动重试可能多计费。HTTPX 的 connect/read/write/pool 超时分别限制建立连接、等待响应数据、发送请求和等待连接池；它们不是“总调用一定小于某个秒数”的简单承诺。模型文字成功也不保证业务正确，题目与标签还要各自经过 Pydantic 校验。

### 统一客户端不意味着把业务判断塞进去

`DeepSeekClient.chat` 接受 messages、是否 JSON 模式和输出上限，但它不接收 note_id 或 user_id。它只负责一项外部通信：验证本机配置，组装 HTTP 请求，等待上游，并把返回解析为非空文字。第 31 篇题目服务才知道“这篇笔记属于谁”；第 32 篇标签服务才知道“标签需要去重、最大 50 字符”。如果把这些业务规则全写进客户端，未来任何一个功能调整都会影响所有模型调用。反过来，如果每个服务自己拼 Authorization 头和超时，密钥处理与故障响应又会漂移，所以把协议细节集中是合理的边界。

`SecretStr` 只降低无意打印时的泄露风险，不会让密钥自动变得安全。调用 `get_secret_value()` 时会拿到真实字符串，此后不要放进日志、异常 detail、前端 JSON 或数据库。若你先前已把密钥贴到公开仓库或分享的日志，应在供应商侧轮换；本教程不需要也不会复写真实密钥。`.env.example` 保留空值，是为了让别人知道变量名而不获得你的凭据。后端配置和 Compose 配置都读取根目录 `.env` 的不同键，新增模型变量不会改变 MySQL 密码。

JSON 模式带 `response_format={"type":"json_object"}`，仍需在 system/user 消息里明确要求 JSON；否则上游可能浪费 token 生成无用空白。即使收到语法合法的 JSON，也要检查 `choices` 非空、message.content 是字符串、业务字段正确。普通文字调用不要求 JSON，所以同一个客户端能供补全和聊天前段使用。`max_tokens` 限制输出而不是输入，正文截断仍由业务服务完成；把整个很长笔记都放进 messages，单靠 max_tokens 无法控制输入成本。

生产工程会问高并发时每次新建 `AsyncClient` 是否浪费连接。当前教学版以 `async with` 确保请求结束即关闭，不容易泄露资源；若后续观察到连接建立开销明显，可在 `lifespan` 建一个共享客户端并在退出时关闭。那时要考虑连接池上限、DNS/代理设置、服务关闭时仍在流式回答的请求，以及密钥轮换。优化应由测量驱动，不应在第一个模型请求还未跑通时先增加全局生命周期复杂度。

### 复核依赖与配置时的实际顺序

在复刻 `backend` 里执行 `uv add httpx` 后，`pyproject.toml` 记录直接依赖，`uv.lock` 记录解析出的准确版本与传递依赖；随后导出 `requirements.txt`。这三份文件不需要手工互相复制。只修改 requirements.txt，开发环境的 `uv sync --locked` 仍可能不会安装 httpx；只修改 pyproject.toml，不更新锁文件，另一台机器也无法复现当前组合。检查 `uv run python -c 'import httpx; print(httpx.__version__)'` 只打印版本号，不触发模型请求或读取私密提示。

本机 `.env` 若已经有 DEEPSEEK_API_KEY，就不要重复追加第二个同名键；重复键的解析顺序容易造成“以为换了钥匙，进程仍用旧值”。先备份当前本机配置，仅调整同一行，再重启服务。教程给的 `<在本机替换成你的真实密钥>` 是占位说明，绝不能原样保存为可用配置。`.env.example` 保持空值，提交时只提交它和代码依赖变化。若本机环境变量里也存在 DEEPSEEK_API_KEY，它可能覆盖文件值，应检查来源而不是把真实值打印出来。

模型调用先用假上游测试协议，再用真实服务测可达性和账户权限。假上游可稳定返回空 choices、错误 JSON 和延迟，让你确认 502/503 的映射；真实调用只测一条短且不含隐私的消息。两类测试证明的东西不同：假上游不能证明 DeepSeek 账户可用，真实小请求也不能覆盖所有格式错误。若模型供应商更新名称或参数，以官方文档和你的实际小请求为准，模型名集中在 DEEPSEEK_MODEL，避免在四个业务服务里到处改常量。

### 处理上游响应的四道检查

第一道是本机配置：空密钥直接返回 503，不发网络请求。第二道是 HTTP 传输：连接、读取、写入或上游非 2xx 状态都在同一通信边界映射成可识别的失败；对外不带上游原始错误正文。第三道是协议结构：响应 JSON 必须有非空 choices、message 和 content，缺字段或不是 JSON 用 502 表明协议不符。第四道是业务校验：题目要四个选项，标签要数量与去重；这些不能由通用客户端判断，而由调用它的服务完成。这样排障时可以问“失败发生在哪一道门”，不必从整个后端搜索一遍。

`httpx.Timeout` 的 connect、read、write、pool 分别用于不同等待阶段。上游建立连接快但生成慢，可能触发 read timeout；高并发时连接池耗尽可能触发 pool timeout。捕获 `httpx.HTTPError` 可以统一处理这些传输问题，但服务端日志仍应记录异常类别和请求 ID，便于辨别是否需要调整时限、连接池或供应商配额。日志不要含认证头。不要把全部超时设成 `None`，那只会让失败更难结束。

上游输出的文字可能包含“我无法回答”，仍是非空字符串，通用客户端不能保证有用性。回顾题服务会检查 JSON 结构，自动标签会检查标签列表，聊天会检查完整结束与非空答案；但语义质量仍需样本评估。客户端抽象能减少协议重复，却不能替代对费用、准确率、用户反馈和供应商变更的工程监控。

## 7. 工程面试思考

回答时要指向本篇具体文件、数据库约束或接口结果，区分当前已实现、验证时才可能观察到的结果与未来扩展。这里讨论设计判断，不背诵通用定义。

**面试官：为什么不在每个路由里直接调 DeepSeek？**

统一客户端让密钥、模型名、超时与错误映射只有一个地方。业务层仍决定 prompt、权限与输出 schema。代价是多一个抽象，但三个后续功能共用它，能减少行为漂移。

**面试官：为什么不在应用启动时用密钥向模型发探测请求？**

外部模型可能临时不可达、限流或计费；若启动强依赖它，笔记和知识库也会不能用。当前启动只保证基础 MySQL/Redis，AI 功能在调用时返回明确错误。若产品要求“AI 必须就绪”，可另设 AI readiness，而不是混入已有 ready。

**面试官：设置了 JSON 模式能否相信字段一定正确？**

不能。官方保证 JSON 语法层面，但字段名、类型、choices 数量和内容是否为空仍需业务层验证。第 31 篇会用 Pydantic 校验 question/choices/answer，并处理截断、空内容或不匹配答案。

**面试官：如何处理上游变更与费用？**

模型名放配置，可在测试环境切换；超时和 max_tokens 限制单次资源。生产还应做调用预算、限流、重试策略和监控。对非幂等或计费请求不能无脑重试；必须区分连接失败、429 与已经处理但响应丢失。

## 8. 常见故障的定位顺序

- **缺密钥：** 确认根目录 .env，不在前端或参考仓库里填。
- **503：** 区分未配置、网络、上游状态；日志不要打印 Authorization。
- **502：** 检查 choices/message/content 形状与当前官方协议。
- **请求卡住：** 检查 connect/read/write/pool 超时；不要把 timeout=None 当修复。
- **模型名失效：** 查看官方 Models & Pricing 与本机 DEEPSEEK_MODEL。

## 9. 本篇边界和下一篇

本篇提供统一的文字模型调用边界，尚未让页面出现 AI 结果。第 31 篇让回顾题服务调用它并对模型 JSON 做严格校验。

本篇没有修改前端文件。新代码完成并经过你本机的验证后，才把它记为你亲手完成；仅阅读教程、助手先前的隔离检查或接口文档出现新路径，都不能代替真实执行。
