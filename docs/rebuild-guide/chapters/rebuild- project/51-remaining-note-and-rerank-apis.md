# 第 51 篇：补齐笔记写作、关联片段与文档重排接口

## 1. 本篇要接通的真实能力

核心笔记、聊天与检索已经串起来，但前端端点表里还有三类后端能力：/note/assist/stream、/note/{id}/related、/chat/reorder。写作辅助只返回建议文本，用户点击保存时才调用已有笔记更新接口；关联片段从当前用户的混合检索结果形成卡片；重排对请求里传入的候选文档做本地向量排序。本篇不让 AI 结果直接修改正文，也不把混合检索的 RRF 名次伪装成真实余弦相似度。重排技术与初始召回的区别见 [Q23](technology-routes/Q23-hybrid-retrieval-and-rerank.md)。

参考前端目前仅列有写作辅助端点，页面不一定主动调用；接口仍按参考项目的纯文本 SSE 协议实现，便于随后页面接入。其余两项的响应字段按现有前端 types/api.ts 对齐。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 文件 | 职责 |
|---:|---|---|---|
| 1 | 【修改】 | backend/app/services/note_ai_service.py | 续写、扩写、缩写的受限提示 |
| 2 | 【修改】 | backend/app/router/note_router.py | 纯文本 SSE 写作端点 |
| 3 | 【新增文件】 | backend/app/rag/related.py | 用户范围内关联候选和真实相似度 |
| 4 | 【修改】 | backend/app/router/note_router.py | 关联片段端点 |
| 5 | 【新增文件】 | backend/app/rag/reorder.py | 候选文本二次排序 |
| 6 | 【修改】 | backend/app/router/chat_router.py | 重排端点 |
| 7 | 【运行验证】 | 双账号、空候选、断流 | 验证响应与隔离 |

这里的关联片段先从第 46 篇混合候选中取来源，随后从 MySQL 重新确认来源归属。向量余弦分只是相关性信号，不能证明两个文本表达同一事实。

## 3. 按顺序修改文件与验证

### 步骤 1：【修改】backend/app/services/note_ai_service.py

**编辑文件的完整地址：**

~~~text
./backend/app/services/note_ai_service.py
~~~

**修改定位与前后对照：** 在 NoteAIService 的 autocomplete 方法前加入 assist_chunks；复用已有 deepseek_client。

~~~diff
+    async def assist_chunks(self, content: str, action: str):
+        tasks = {
+            "continue": "沿原文续写一小段，保持语气，不重复原文",
+            "expand": "扩写原文，补充解释，不捏造事实",
+            "summarize": "把原文缩写成更短的一段，保留关键意思",
+        }
+        instruction = tasks[action]
+        async for part in deepseek_client.stream_chat([
+            {"role": "system", "content": (
+                "你是笔记写作助手。只输出建议文本；不得宣称已保存笔记。"
+                + instruction
+            )},
+            {"role": "user", "content": content[:6000]},
+        ], max_tokens=650):
+            yield part
+
     async def autocomplete(self, context: str) -> AutocompleteResponse:
~~~

**整体解释：** 三种按钮虽然都“让 AI 写字”，规则不同：续写像接着写下一段，扩写像把提纲展开，缩写像压成摘要。这里仅流出文本碎片，不知道也不需要知道笔记 ID，所以它不可能在服务器里偷偷覆盖原正文。敏感正文只发给后端配置的模型服务；长度上限避免整本资料误入一次请求。

### 步骤 2：【修改】backend/app/router/note_router.py

**编辑文件的完整地址：**

~~~text
./backend/app/router/note_router.py
~~~

**修改定位与前后对照：** 在 /autocomplete 附近加入写作请求模型和路由；注意必须放在 /{note_id} 动态路由前。参考项目的此接口发送原始文本 SSE，不能误用 AIChat 的 JSON frame。

~~~diff
-from fastapi.responses import JSONResponse, Response
+from fastapi.responses import JSONResponse, Response, StreamingResponse
+from pydantic import BaseModel, Field
@@
 note_router = APIRouter(prefix="/note", tags=["note"])
+
+
+class AssistRequest(BaseModel):
+    content: str = Field(min_length=1, max_length=6000)
+    action: Literal["continue", "expand", "summarize"] = "continue"
@@
 @note_router.post("/autocomplete")
@@
     return success_response(data=await note_ai_service.autocomplete(payload.context))
+
+
+@note_router.post("/assist/stream")
+async def assist_stream(
+    payload: AssistRequest,
+    user_id: str = Depends(get_current_user_id),
+) -> StreamingResponse:
+    async def events():
+        try:
+            async for part in note_ai_service.assist_chunks(
+                payload.content, payload.action,
+            ):
+                for line in part.splitlines(keepends=True):
+                    yield "data: " + line.replace("\n", "") + "\n\n"
+            yield "data: [DONE]\n\n"
+        except Exception:
+            yield "data: [ERROR: 模型写作暂不可用]\n\n"
+
+    return StreamingResponse(
+        events(), media_type="text/event-stream",
+        headers={"Cache-Control": "no-cache"},
+    )
~~~

**整体解释：** 路由先借 JWT 确认是已登录用户，再把固定的 action 交给服务。每个输出行变为独立 SSE data 行，最后的 [DONE] 告诉调用方完整结束；中途失败给 [ERROR: …]，不返回半段文字当成功。这里没有数据库提交，用户是否采用建议仍由编辑器决定。若前端未来改用统一 JSON SSE，需要同时修改前后端，不能只改一侧。

### 步骤 3：【新增文件】backend/app/rag/related.py

**编辑文件的完整地址：**

~~~text
./backend/app/rag/related.py
~~~

**完整文件内容：**

~~~python
"""关联卡片：候选召回后重新确认 MySQL 来源归属。"""
import math

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_document import KnowledgeDocument
from app.models.note import Note
from app.rag.embedding import embed
from app.rag.hybrid_retrieval import search


def cosine(a: list[float], b: list[float]) -> float:
    value = sum(x * y for x, y in zip(a, b))
    return max(0.0, min(1.0, value))


async def related_fragments(
    db: AsyncSession, user_id: str, note_id: str
) -> list[dict]:
    note = await db.scalar(select(Note).where(
        Note.id == note_id, Note.user_id == user_id,
    ))
    if note is None:
        raise HTTPException(status_code=404, detail="笔记不存在")
    seed = (note.title + " " + note.content[:300]).strip()
    if not seed:
        return []
    hits = await search(db, user_id, seed[:100])
    seed_vector = await embed(seed[:500])
    result: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for hit in hits:
        key = (hit.source_kind, hit.source_id)
        if key in seen or key == ("note", note_id):
            continue
        seen.add(key)
        if hit.source_kind == "note":
            source = await db.scalar(select(Note).where(
                Note.id == hit.source_id, Note.user_id == user_id,
            ))
            if source is None:
                continue
            title, content, kind = source.title, source.content, "note"
        else:
            source = await db.scalar(select(KnowledgeDocument).where(
                KnowledgeDocument.id == hit.source_id,
                KnowledgeDocument.user_id == user_id,
            ))
            if source is None:
                continue
            title, content, kind = source.filename, hit.snippet, "knowledge_base"
        score = cosine(seed_vector, await embed(content[:500] or title))
        if not math.isfinite(score):
            continue
        result.append({
            "id": hit.source_id, "title": title,
            "content_preview": content[:180], "content": content[:1200],
            "similarity": round(score, 4), "source": kind,
        })
    return sorted(result, key=lambda item: -item["similarity"])[:5]
~~~

**整体解释：** 混合检索像先找出五张候选卡，接着 MySQL 再检查每张卡是否仍属于当前账号，删除了的来源也被过滤。为了满足前端“相似度百分比”，这里重新计算归一化向量的点积，而不直接拿 RRF 名次当百分比。知识库卡片展示命中的 snippet，不把整份上传文件一次发回浏览器。候选为零时不需要强求模型调用；本地嵌入模型故障应让此端点清楚失败，不能偷换成假的 100%。

### 步骤 4：【修改】backend/app/router/note_router.py

**编辑文件的完整地址：**

~~~text
./backend/app/router/note_router.py
~~~

**修改定位与前后对照：** 增加导入和固定后缀路由，可放在 /{note_id}/download 旁。

~~~diff
 from app.services.note_ai_service import note_ai_service
+from app.rag.related import related_fragments
@@
+@note_router.get("/{note_id}/related")
+async def related_note_fragments(
+    note_id: str,
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> JSONResponse:
+    return success_response(
+        data=await related_fragments(db, user_id, note_id)
+    )
+
+
 @note_router.get("/{note_id}/download")
~~~

**整体解释：** 路由不自己拼搜索 SQL，只给服务传入 JWT user_id 和笔记 ID。服务先验证起点笔记归属，再核对每条结果归属；这两处检查都需要，不能因为向量索引已经过滤过用户就省掉 MySQL 复核。

### 步骤 5：【新增文件】backend/app/rag/reorder.py

**编辑文件的完整地址：**

~~~text
./backend/app/rag/reorder.py
~~~

**完整文件内容：**

~~~python
"""对调用方给出的少量候选做本地向量二次排序。"""
from app.rag.embedding import embed
from app.rag.related import cosine


async def reorder(query: str, documents: list[str]) -> list[dict]:
    if not documents:
        return []
    query_vector = await embed(query)
    ranked = []
    for index, document in enumerate(documents):
        score = cosine(query_vector, await embed(document[:2000]))
        ranked.append((index, {
            "document": document,
            "similarity": round(score, 4),
        }))
    ranked.sort(key=lambda item: (-item[1]["similarity"], item[0]))
    return [item for _, item in ranked]
~~~

**整体解释：** 初始召回负责“从大仓库捞少量可能有关的纸条”，重排负责“给这批纸条重新排座位”。这里不查任何用户资料，只计算请求中提供的短列表；如果调用方传了其他人的内容，此端点无法识别来源，所以内部业务绝不能把它当权限检查。相同分数保持原次序，便于重复验证。与参考项目可配置云端 reranker 的结果可能不同，本篇用已下载的本地嵌入模型保持 DeepSeek 只负责生成。

### 步骤 6：【修改】backend/app/router/chat_router.py

**编辑文件的完整地址：**

~~~text
./backend/app/router/chat_router.py
~~~

**修改定位与前后对照：** 在 ResumeRequest 附近增加模型，在已有 /sessions 路由前注册 /reorder。

~~~diff
 from pydantic import BaseModel, Field
+from app.rag.reorder import reorder
@@
 class ResumeRequest(BaseModel):
@@
     decisions: list[ApprovalDecision] = Field(min_length=1, max_length=1)
+
+
+class ReorderRequest(BaseModel):
+    query: str = Field(min_length=1, max_length=100)
+    documents: list[str] = Field(max_length=20)
@@
+@chat_router.post("/reorder")
+async def reorder_documents(
+    payload: ReorderRequest,
+    user_id: str = Depends(get_current_user_id),
+) -> JSONResponse:
+    if any(not item or len(item) > 2000 for item in payload.documents):
+        raise HTTPException(status_code=422, detail="候选文档过长或为空")
+    return success_response(data={
+        "documents": await reorder(payload.query, payload.documents)
+    })
+
+
 @chat_router.get("/sessions")
~~~

**整体解释：** 数量与长度限额把一次向量计算的成本关在可预期范围内；返回对象中的 documents 数组沿用参考端点的字段。这个接口只排序输入，不能替代第 46 篇“先按 user_id 检索候选”的步骤。若日后切换云端 reranker，只换服务实现，不要改前端请求协议。

### 步骤 7：【运行验证】三个端点的边界

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv run python -m compileall -q app main.py
~~~

用一个测试账号调用写作流的三种 action，确认收到若干 data 行和 [DONE]，再检查笔记正文并未变化。另建两账号资料，打开第一账号的“关联片段”，列表必须没有第二账号来源；传第二账号 note_id 应得到 404。重排分别用空数组、重复句子、显著相关和无关文本验证排序稳定性。大于 20 条或单条超过 2000 字符的请求应被拒绝。
