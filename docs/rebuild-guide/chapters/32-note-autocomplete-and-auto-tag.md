# 第 32 篇：笔记内联补全与手动重新生成标签

> 前置：第 31 篇完成后的复刻后端。本文是待操作教程，写作时对照了正式复刻目录和参考项目；文中的预期结果不是正式工程已实测的结果。
> 成果：POST /note/autocomplete 返回编辑器可用的短续写；POST /note/{note_id}/auto-tag 仅为当前用户笔记生成并保存标签。
> 范围：只指导后端；前端继续直接使用已经复制的源码。新增文件给完整代码，修改文件只给本次 diff，不重复整份最终源码。

## 1. 本篇要接通的真实能力

复制来的笔记编辑器在用户停顿时会调用 `/note/autocomplete`，只期待 `{completion: "..."}`；参考后端还提供手动重新生成标签。二者都用第 30 篇的模型边界，却有不同的状态语义：补全只给建议，不能替用户保存正文；重新生成标签要查归属、解析模型 JSON、更新 MySQL。把两者放在一篇，可以看清“模型返回文字”和“业务数据持久化”之间的分界。

本篇从复刻项目现有代码继续，路径和导入均从下面这个固定目录算起。不要在参考仓库执行修改；那份源码用于比较接口与数据流。代码注释中【新增】标出本步新行为，diff 的正负号只用于定位，不要粘进 Python 文件。涉及账号或模型密钥时只用本机 `.env`，不把真实值写进教程或 Git。

**复刻根目录：**

```text
.
```

**本篇接口或产物契约：**

- 自动补全只接收有限长度 context，返回短 completion，不提交 Note，也不读取其他用户笔记。
- 自动标签必须先按 note_id+user_id 找笔记；模型返回 1–5 个非空、去重、长度受限的标签，服务提交后才返回。
- 模型无密钥或失败时按第 30 篇规则返回明确错误，不把空字符串伪装成成功。
- 自动标签接口本阶段同步完成，参考实现的后台任务与图谱联动留待后续。

**本篇与参考实现的差异：** 参考项目内联补全使用本地小模型且目标延迟很低；用户已选择 DeepSeek，本篇用远程 API，因此网络耗时和费用不同，必须限长并让前端能处理失败。参考自动标签在后台处理；本篇同步提交，更容易验证持久化。

**技术路线阅读：** 模型路线继续看 [Q15](technology-routes/Q15-deepseek-model-client.md)，不要把供应商选择误认为编辑器交互语义。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 路径 | 本步职责 |
|---:|---|---|---|
| 1 | 【修改】 | `backend/app/schemas/models.py` | 声明补全输入和自动标签输出 |
| 2 | 【新增文件】 | `backend/app/services/note_ai_service.py` | 把补全与标签提示、校验及数据库提交集中在服务层 |
| 3 | 【修改】 | `backend/app/router/note_router.py` | 补全固定路径接入编辑器 |
| 4 | 【修改】 | `backend/app/router/note_router.py` | 补齐手动重新生成标签的动态路径 |

先看清楚上表：新文件的父目录若已存在就复用；步骤之间的 import 按顺序出现。每做完一个文件就做该步的小检查，不要把所有代码贴完才第一次启动。修改已有文件时请按 diff 的上下文搜索函数名或配置项，行号只供参考，因为上一章或你自己的改动可能改变行号。

## 3. 按顺序修改文件与验证

### 步骤 1：【修改】 `backend/app/schemas/models.py`

**文件职责：** 声明补全输入和自动标签输出

**编辑文件的完整地址：**

```text
./backend/app/schemas/models.py
```

**修改定位与前后对照：** 搜索代码块中的原函数或配置项，按 `-` 删除旧行、按 `+` 增加新行。只展示本篇变更。

```diff
@@
 class ReviewQuestionResponse(BaseModel):
@@
         return self
+
+
+class AutocompleteRequest(BaseModel):
+    context: str = Field(min_length=1, max_length=2000)
+
+    @field_validator("context", mode="before")
+    @classmethod
+    def trim_context(cls, value):
+        return value.strip() if isinstance(value, str) else value
+
+
+class AutocompleteResponse(BaseModel):
+    completion: str
+
+
+class AutoTagResponse(BaseModel):
+    note_id: str
+    tags: list[str]
```

**整体解释：** 补全请求模型限制传给外部服务的编辑器上下文，先去首尾空白再检查非空；否则用户每停一次、空内容也会发一次模型请求。响应模型恰好给前端需要的 completion，不偷偷改 Note.content。标签响应把 note_id 和最终标签一起返回，方便确认数据库改的是哪篇。

**工程位置与触发时刻：** FastAPI 在进入路由前验证 AutocompleteRequest；标签响应在服务提交后构造。

**完成这一小步的判断：** 空 context 被 422 拒绝，超长 context 也被挡住。

**如果这里失败：** 如果空格仍进模型，检查 field_validator 是否 mode=before。

### 步骤 2：【新增文件】 `backend/app/services/note_ai_service.py`

**文件职责：** 把补全与标签提示、校验及数据库提交集中在服务层

**编辑文件的完整地址：**

```text
./backend/app/services/note_ai_service.py
```

**完整文件内容：**

```python
"""笔记 AI 辅助：建议与持久化操作分开。"""
import json
from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.note import Note
from app.schemas.models import AutoTagResponse, AutocompleteResponse
from app.services.deepseek_client import deepseek_client

class TagPayload(BaseModel):
    tags: list[str] = Field(min_length=1, max_length=5)

    @field_validator("tags")
    @classmethod
    def valid_tags(cls, tags: list[str]) -> list[str]:
        cleaned = [tag.strip() for tag in tags]
        if any(not tag or len(tag) > 50 for tag in cleaned) or len(set(cleaned)) != len(cleaned):
            raise ValueError("标签需要非空、唯一且不超过 50 字符")
        return cleaned

class NoteAIService:
    async def autocomplete(self, context: str) -> AutocompleteResponse:
        result = await deepseek_client.chat([
            {"role": "system", "content": "只续写用户编辑器光标前的文字，返回一句简短续写，不要重复原文。"},
            {"role": "user", "content": context[-2000:]},
        ], max_tokens=80)
        return AutocompleteResponse(completion=result[:300])

    async def auto_tag(
        self, db: AsyncSession, user_id: str, note_id: str
    ) -> AutoTagResponse:
        note = await db.scalar(select(Note).where(Note.id == note_id, Note.user_id == user_id))
        if note is None:
            raise HTTPException(status_code=404, detail="笔记不存在")
        raw = await deepseek_client.chat([
            {"role": "system", "content": "为笔记提取 1 到 5 个标签。只返回 JSON，例如 {\"tags\":[\"Python\",\"后端\"]}。"},
            {"role": "user", "content": (note.title + "\n" + note.content)[:3000]},
        ], json_mode=True, max_tokens=180)
        try:
            tags = TagPayload.model_validate(json.loads(raw)).tags
        except (ValueError, ValidationError) as exc:
            raise HTTPException(status_code=502, detail="模型标签格式异常") from exc
        note.tags = tags
        await db.commit()
        return AutoTagResponse(note_id=note.id, tags=tags)

note_ai_service = NoteAIService()
```

**整体解释：** 这份服务同时展示两类 AI 功能的差别。补全像编辑器旁的建议卡：模型说什么只返回给前端，由用户决定是否插入正文；它没有数据库会话，也不会改已有笔记。自动标签像正式填写分类索引：先查当前用户拥有的 Note，再让模型生成 JSON，用 TagPayload 检查数量、去重和长度，最后一次 commit 写回 tags。模型文本从来不应未经校验就直接保存。

**工程位置与触发时刻：** /note/autocomplete 调用建议分支；/{note_id}/auto-tag 调用写入分支；模块导入本身不会调用模型。

**完成这一小步的判断：** 补全短于 300 字符且 Note 不变；标签保存后 GET /note/{id} 可读到同样列表。

**如果这里失败：** 若标签被 502 拦截，检查模型 JSON 和 TagPayload；不能为了“成功”去掉校验。

### 步骤 3：【修改】 `backend/app/router/note_router.py`

**文件职责：** 补全固定路径接入编辑器

**编辑文件的完整地址：**

```text
./backend/app/router/note_router.py
```

**修改定位与前后对照：** 搜索代码块中的原函数或配置项，按 `-` 删除旧行、按 `+` 增加新行。只展示本篇变更。

```diff
@@
-from app.schemas.models import (
+from app.schemas.models import (
+    AutocompleteRequest,
@@
 from app.services.note_service import note_service
+from app.services.note_ai_service import note_ai_service
@@
-@note_router.get("/search")
+@note_router.post("/autocomplete")
+async def autocomplete(
+    payload: AutocompleteRequest,
+    user_id: str = Depends(get_current_user_id),
+) -> JSONResponse:
+    return success_response(data=await note_ai_service.autocomplete(payload.context))
+
+
+@note_router.get("/search")
```

**整体解释：** 路由从前端收到 `{context}` 并先要求登录，再把经过 Pydantic 限长的文字交给建议服务。它没有 get_db，正是因为补全不写笔记；user_id 依赖仍要保留，防止匿名调用消耗模型额度。`/autocomplete` 插在动态路由之前，确保请求真的走补全函数。

**工程位置与触发时刻：** 前端编辑器发 POST 时触发；路由注册时不生成任何建议。

**完成这一小步的判断：** 路径出现在 OpenAPI；响应 data.completion 是字符串。

**如果这里失败：** 若返回 /{note_id} 的消息，调整装饰器顺序；若 503 查模型配置。

### 步骤 4：【修改】 `backend/app/router/note_router.py`

**文件职责：** 补齐手动重新生成标签的动态路径

**编辑文件的完整地址：**

```text
./backend/app/router/note_router.py
```

**修改定位与前后对照：** 搜索代码块中的原函数或配置项，按 `-` 删除旧行、按 `+` 增加新行。只展示本篇变更。

```diff
@@
 @note_router.put("/{note_id}/pin")
 async def toggle_pin(
@@
     return success_response(message="置顶已更新", data=NoteResponse.model_validate(note))
+
+
+@note_router.post("/{note_id}/auto-tag")
+async def regenerate_tags(
+    note_id: str,
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> JSONResponse:
+    data = await note_ai_service.auto_tag(db, user_id, note_id)
+    return success_response(message="标签已更新", data=data)
```

**整体解释：** 这个路径虽然含动态 note_id，但最终权限不由 URL 本身决定：服务仍在 SELECT 中加 user_id。模型产出通过校验并提交 MySQL 后才返回“标签已更新”，不会像后台任务提交那样提前宣称完成。后续如果恢复参考项目的异步任务语义，响应文本与前端刷新时机要一起调整。

**工程位置与触发时刻：** POST 触发当前用户的一篇笔记标签重算；其他笔记不受影响。

**完成这一小步的判断：** GET 原笔记详情能读到更新后的 tags。

**如果这里失败：** 找不到本人的 Note 是 404；模型错误不应清空旧 tags。

## 4. 请求和状态如何穿过这些文件

下面只追踪本篇真正涉及的调用链，帮助把刚改的文件连起来；这段解释不需要复制进源码。

1. **编辑器：** onAutocomplete 将光标前 context 发到 /note/autocomplete。
2. **输入边界：** AutocompleteRequest 去空白、限长；JWT 依赖阻止匿名调用。
3. **模型建议：** NoteAIService 构造短续写任务，DeepSeekClient 返回文字，截成可插入的小段。
4. **前端确认：** 编辑器可展示建议；后端不改正文，最终仍靠用户保存笔记。
5. **标签请求：** 手动调用 /note/{id}/auto-tag，服务先按用户查 Note。
6. **模型结构：** JSON 模式生成 tags，TagPayload 限制数量与字符。
7. **持久化：** 服务 commit 后返回标签，下一次 GET/列表可读到。

**事务与隔离边界：** 补全和标签当前都会调用远程模型，延迟与费用不同于参考项目的本地小模型；不要在文档中承诺 300–500 ms。标签服务同步提交，失败时不改旧值，但模型调用成功、数据库提交失败仍可能产生一次模型费用。未来若改异步任务，需要持久任务状态、重试和前端刷新约定。

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

**确认固定路由必须放在动态 note_id 路由之前**：`./backend/app/router/note_router.py`。`/note/autocomplete` 是固定路径，`/note/{note_id}` 是捕获一个路径片段的动态路径。如果固定路由注册得太晚，FastAPI 可能先把 autocomplete 当成 note_id 交给详情函数。先看真实顺序，再决定插入位置；服务层再正确也救不了路由匹配错误。

可用的定位或请求片段：

```bash
rg -n "@note_router|async def get_note|/search|/stats" backend/app/router/note_router.py
```

观察点：能定位 /search 与动态 /{note_id} 的边界。 若不符合，如果新路径返回“笔记不存在”，先查路由顺序而非模型 API。

**检查无模型密钥时不会误写标签**：`./backend/app/services/note_ai_service.py`。如果模型服务不可用，自动标签在取到模型结果之前就会抛错，commit 还没有发生，旧 tags 应保留。这个检查需用真实 MySQL 临时笔记与假上游故障一起验，不可只看静态代码。补全也应该明确失败，让编辑器选择忽略建议，而不是返回空串冒充成功。

可用的定位或请求片段：

```bash
uv run python -m compileall -q app/services/note_ai_service.py app/router/note_router.py
```

观察点：编译通过，故障时旧标签仍在数据库。 若不符合，若旧标签变成空列表，检查是否在模型调用之前就修改 note.tags。

**检查空输入与超长输入被拒绝**：`./backend/app/router/note_router.py`。空白补全没有学习价值却可能产生调用费用，应该在请求模型处 422。把校验放在 HTTP 边界，服务只处理已经符合长度范围的文字。对超长内容亦应拒绝，而不是悄悄从几万字取尾部却让用户以为整篇被理解。

可用的定位或请求片段：

```bash
curl -i -X POST http://127.0.0.1:8100/note/autocomplete -H "Authorization: Bearer $RAG_TOKEN" -H "Content-Type: application/json" -d '{"context":"   "}'
```

观察点：HTTP 422，模型假服务没有收到请求。 若不符合，若 200，检查 route payload 类型是否误用 dict。

**用临时笔记验证补全不会保存正文**：`./backend/app/router/note_router.py`。补全只看前端送来的 context，不知道要改哪篇笔记；即使它给出很好的续写，也不能自动保存。先记临时笔记 content，再调用补全，随后 GET 确认 content 完全不变。这样能清楚区分“建议”和“用户确认保存”。

可用的定位或请求片段：

```text
POST /note/autocomplete then GET /note/<临时ID>
```

观察点：data.completion 有文字；临时 Note.content 前后相同。 若不符合，若笔记正文变化，说明路由误用了 update_note。

**用另一个令牌验证标签归属**：`./backend/app/router/note_router.py`。跨账号请求不应该先调模型再返回 404，更不能把 A 的标题与正文送给模型。用本机两账号和假上游计数器验证请求顺序：A 的笔记配 B 令牌时模型调用数不增加，A 的旧 tags 不变。

可用的定位或请求片段：

```text
POST /note/<A_NOTE_ID>/auto-tag with B token
```

观察点：HTTP 404，模型没调用，数据库没变化。 若不符合，若模型已调用，调整授权查询顺序。

**验证合法标签写入并清理测试数据**：`./backend/app/router/note_router.py`。让假上游返回两个互不重复标签，确认 `data.tags` 与之后 GET 笔记的 tags 一致。再让它返回重复、空白或超过 50 字符的标签，应得到 502 且旧值保持。清理时只删本篇新建的临时笔记，不碰原有笔记。

可用的定位或请求片段：

```text
POST /note/<OWN_NOTE_ID>/auto-tag then GET /note/<OWN_NOTE_ID>
```

观察点：合法提交、非法保留旧值、测试笔记已删除。 若不符合，若返回值正确但 GET 看不到，检查 commit 和响应是否使用同一个 Note。

### 验收 1：固定路由注册

**准备与操作：** 请求 OpenAPI。

```text
GET /openapi.json
```

**期望结果：** 包含 POST /note/autocomplete 与 POST /note/{note_id}/auto-tag。

**为什么要验这一项：** 路由顺序错误会把 autocomplete 当笔记 ID。

**不符合时从哪里查：** 看 note_router 中固定/动态装饰器位置。

### 验收 2：匿名补全

**准备与操作：** 不带 JWT。

```text
POST /note/autocomplete
```

**期望结果：** 401。

**为什么要验这一项：** 防止公共模型代理被滥用。

**不符合时从哪里查：** 检查 get_current_user_id。

### 验收 3：空 context

**准备与操作：** 只传空白字符。

```json
{"context":"   "}
```

**期望结果：** 422 且不调用模型。

**为什么要验这一项：** 边界校验应先于付费请求。

**不符合时从哪里查：** 查 normalize validator。

### 验收 4：超长 context

**准备与操作：** 超过 2000 字符。

```text
POST /note/autocomplete
```

**期望结果：** 422。

**为什么要验这一项：** 控制外发数据和成本。

**不符合时从哪里查：** 检查 max_length 是否作用在 strip 后。

### 验收 5：正常补全

**准备与操作：** 假上游给一句短文字。

```text
POST /note/autocomplete
```

**期望结果：** data.completion 为非空短文字。

**为什么要验这一项：** 前端 TiptapEditor 读取这个键。

**不符合时从哪里查：** 若前端不显示，查 data 包装层与接口路径。

### 验收 6：正文不变

**准备与操作：** 补全前后读取同一笔记。

```text
GET /note/<临时ID>
```

**期望结果：** content 不变。

**为什么要验这一项：** 建议不自动写库。

**不符合时从哪里查：** 查 NoteAIService.autocomplete 是否误用 db。

### 验收 7：标签归属

**准备与操作：** B 请求 A 的笔记。

```text
POST /note/<A_ID>/auto-tag
```

**期望结果：** 404，A 的 tags 不变。

**为什么要验这一项：** 用户隔离必须早于模型调用。

**不符合时从哪里查：** 查 Note.id+Note.user_id 条件。

### 验收 8：合法标签

**准备与操作：** 假上游返回两个标签。

```json
{"tags":["后端","复刻"]}
```

**期望结果：** 成功并在 MySQL 中保留。

**为什么要验这一项：** 模型输出需要真正提交。

**不符合时从哪里查：** 查 commit 与 NoteResponse 序列化。

### 验收 9：重复标签

**准备与操作：** 假上游返回重复。

```json
{"tags":["后端","后端"]}
```

**期望结果：** 502，旧标签保留。

**为什么要验这一项：** 阻止无效模型结果污染数据。

**不符合时从哪里查：** 查 TagPayload 去重。

### 验收 10：模型断开

**准备与操作：** 假上游超时。

```text
POST /note/<OWN_ID>/auto-tag
```

**期望结果：** 503，旧标签保留。

**为什么要验这一项：** 故障不能清空原值。

**不符合时从哪里查：** 查是否在调用模型前赋值。

## 6. 深入动手与状态核对

### 补全与自动标签是两种不同的写入责任

编辑器补全只收到光标前的 `context`。用户可能正在写一篇尚未保存的笔记，此时没有 note_id；因此后端返回的是“建议”，没有数据库会话，也不提交 Note。前端是否把建议插入编辑器，由用户操作决定。即使模型返回看似完整的一段正文，也不能由补全接口自动覆盖已有内容。验证时先读一次临时笔记正文，再调用补全，再读一次，数据库内容应逐字相同。若页面显示了新文字但数据库没变，那是编辑器的本地草稿状态，保存按钮才会调用笔记更新接口。

自动标签恰好相反：它收到 `note_id`，必须先用 `Note.id` 与 `Note.user_id` 同时查到本人笔记，才可以读取标题/正文发给模型。用 B 的令牌请求 A 的 ID，应该在模型调用前就 404，假上游计数不增加。这既守住隐私，也避免无效的计费请求。模型返回的 JSON 经过 `TagPayload` 限定 1–5 个非空、互不重复、长度不超过 50 的标签，全部合格后才赋给 `note.tags` 并提交。若某个标签无效，不应只保存其余标签并让用户误以为生成结果完整；本阶段将整组判为 502，旧 tags 保持不变。

### 实际路由顺序和错误恢复

固定 `/note/autocomplete` 必须放在 `/note/{note_id}` 这类动态单段路由之前，否则 FastAPI 可能把 `autocomplete` 当成笔记 ID。OpenAPI 中能看到固定路径还不够，必须真实 POST 确认走到正确函数。空白 context 在 Pydantic 的 before 归一化后应该 422，不调用模型；超长输入也应该在 HTTP 边界拒绝，不能默默裁掉大部分文本却表现得像理解了全文。

让假上游给自动标签返回重复、空白或超长标签，再 GET 同一笔记。GET 看到的仍应是旧标签；若先设置了 `note.tags=[]` 才去调模型，超时后便可能丢掉用户原有分类。模型语义错误仍可能通过结构校验，所以页面应允许用户改动或撤销标签。参考项目可能使用后台任务做自动标签，本篇同步完成后才返回成功；响应慢是当前设计成本，不能把“已发起请求”说成“标签已保存”。

### 把模型输出放进“建议区”和“持久区”两道门

补全只看用户当前输入的一段上下文，即使输入里有尚未保存的文字，服务也不需要读取笔记数据库。`max_tokens=80` 和结果截断为 300 字符限制了单次建议长度，但并不等于完整的费用预算；输入最多 2000 字符，频繁按键仍可能触发大量请求。前端应做防抖或取消过时请求，后端若要保护费用还应按用户限流。当前篇章建立接口语义：建议返回后由用户决定是否使用，不在后台偷偷保存草稿。

自动标签先查当前用户 Note，再用标题与正文的前一段内容让模型提取标签。这意味着很长笔记后半部分的主题可能被遗漏；本篇把这个限制写清，未来可用摘要或分段聚合提高覆盖。模型 JSON 有 `tags` 键并不保证它真是 `list[str]`；TagPayload 用 Pydantic 做类型、个数、空白、重复和长度检查。只有通过后才赋值和 commit。若赋值后的 commit 报数据库错误，事务回滚，应该让前端看到失败，不把内存对象的 tags 当成已保存事实。

对跨账号请求，测试不能只看最终 HTTP 404。你还要用假上游的调用计数证明模型根本没收到那篇别人的正文，否则已经发生隐私外传。权限查询要在模型调用之前，且 SQL 同时按 `id` 和 `user_id` 过滤。若业务改成后台任务，任务进程同样需要携带经过验证的用户 ID，并在实际执行时重新确认资源归属；不能因为任务由路由发起就永远信任过时的权限状态。

固定路径与动态路径冲突不是语法错误，服务器可以正常启动、OpenAPI 也列出两条路径，但真实请求可能进错函数。因此验收要实际 `POST /note/autocomplete`，不能只用文档列表判断。自动标签路径的 `note_id` 也应保留为服务的目标线索而非授权依据。补全和标签使用同一个 DeepSeekClient，只共享协议边界，不共享是否写库的业务责任。

### 两条接口都需要负向演练

补全接口先测试空白 context、超长 context、匿名请求，三者都应该在模型调用前被拒绝。再用合法短文字让假上游返回固定续写，确认响应在 `data.completion` 而非数据库 Note.content。即使是登录用户，补全建议也不应该自动变成笔记修改；用户在编辑器里看到建议后选择接受，才由前端后续保存流程把内容写回。这种分离让 AI 的猜测不会直接覆盖人写的正文。

自动标签用临时笔记先保存一份人工标签，再让假上游分别返回合法、重复、空白、超过数量和超过单项长度的 JSON。每个失败样本后都 GET 笔记详情，看 tags 是否保留上一次已经提交的值。不要只看自动标签接口的错误响应，因为某些错误路径可能已经先把 ORM 对象改脏；只有下一次独立请求读数据库才证明没有错误落库。合法样本则要同时看本次返回的 tags 与独立 GET 是否完全一致。

为了验证“先授权再调用模型”，用 B 令牌请求 A 的 note_id，并让假上游记录请求计数。期望 HTTP 404，计数零，A 的 tags 不变。若服务先按 note_id 全局查笔记、发给模型，最后再检查 user_id，虽然客户端收到 404，隐私和费用都已经损失。SQL 的 `Note.user_id == user_id` 必须与 ID 条件在同一个 SELECT 里。对于本人的笔记，正文可能很长，当前只送标题与正文前 3000 字符；这是明确的输入窗口，不要向用户暗示模型读过整篇文章。

前端编辑器可能连续触发多个补全请求，后返回的旧请求可能覆盖新请求建议。后端当前只返回每次请求的结果，UI 需要按请求顺序或取消信号处理过时响应。自动标签则是写操作，不能照搬补全的“来了就显示”处理；用户再次手动编辑标签与正在进行的模型请求可能竞态，生产版可加版本号或明确操作锁。本篇先保证每次请求都经过归属检查、结构验证和一次提交。

### 把单次请求的输入、输出和写库三栏记清

补全的输入是 `context`，输出是 `completion`，没有 note_id，也不改变 notes 表。自动标签的输入是路径里的 note_id 和 JWT 身份，模型看到的是被授权笔记的标题/正文摘要，输出是合格的 tags，并且更新该 Note。把两条接口放在同一个服务文件，不意味着它们都有相同副作用；阅读方法签名时可看 `autocomplete` 不接 AsyncSession，`auto_tag` 接 db 并调用 commit。若补全方法未来要从知识库找上下文，就必须增加清楚的授权查询和成本边界，不能直接在这里用全局数据库会话。

模型可能给出语义上错误但结构合法的标签。例如笔记讲 SQL 事务，模型给“前端动画”，TagPayload 不会识别事实错误。工程上可以让用户编辑、撤销或拒绝自动标签；也可以在产品有固定标签体系时让模型只从白名单选。本篇不假称 Pydantic 能判断语义正确。相反，结构错误如重复标签或空白标签是确定可判的，必须在写库前拒绝。一次成功提交后再次 GET 应读到相同标签，验证“返回成功”和“持久化成功”一致。

当上游发生 503，自动标签的旧值应留在数据库；补全则应让前端知道建议不可用而不影响编辑器当前文字。两个功能均不应拖垮基本笔记 CRUD。若上游调用时间增长，自动标签的同步等待会让按钮持续加载，可以后续改为后台任务，但那时响应只代表任务已受理，不代表标签已写入，前端要显示任务状态。当前实现同步返回，验证边界更直接。

## 7. 工程面试思考

回答时要指向本篇具体文件、数据库约束或接口结果，区分当前已实现、验证时才可能观察到的结果与未来扩展。这里讨论设计判断，不背诵通用定义。

**面试官：为什么补全不接收 note_id？**

前端可能在新笔记未保存前就请求建议，只有光标前 context 可用。补全是无持久化建议；如果以后要引用整篇笔记或知识库，就要显式传授权范围并限制上下文，不能默认读取用户所有数据。

**面试官：为何把固定 /autocomplete 放在 /{note_id} 之前？**

路由匹配按注册顺序，动态单片段路径可能吃掉固定路径。明确顺序是接口正确性的组成部分；OpenAPI 有路径不保证请求一定匹配到它，必须实际请求验收。

**面试官：自动标签同步调用模型有什么代价？**

用户要等待上游网络和数据库提交，响应更慢；好处是返回时标签确实持久化，容易理解。参考实现使用后台任务，适合延迟较长，但需要任务状态、重试和前端刷新，否则“任务已提交”容易被误解为“标签已写好”。

**面试官：模型给出看似合理但与正文不符的标签怎么办？**

结构校验只能防空值、重复和长度，不能证明语义正确。产品应允许用户编辑/撤销标签，必要时用评估集、人审或候选标签白名单；不要把模型输出当数据库事实。

## 8. 常见故障的定位顺序

- **补全 404：** 检查路由注册顺序，固定路径应先于动态 note_id。
- **补全太慢：** 远程模型延迟与参考本地模型不同；检查网络、超时和前端防抖。
- **标签 502：** 看 JSON 字段、数量、去重和长度约束。
- **旧标签丢失：** 确认先校验新结果再给 note.tags 赋值。
- **跨账号泄露：** 查 Note.user_id 过滤是否先于模型请求。

## 9. 本篇边界和下一篇

本篇让笔记编辑器得到 AI 建议，并能把合格的标签保存到用户自己的笔记。第 33 篇开始聊天的数据骨架：先建立会话和消息表，再谈聊天流。

本篇没有修改前端文件。新代码完成并经过你本机的验证后，才把它记为你亲手完成；仅阅读教程、助手先前的隔离检查或接口文档出现新路径，都不能代替真实执行。
