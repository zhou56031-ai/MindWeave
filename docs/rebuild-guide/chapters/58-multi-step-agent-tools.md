# 第 58 篇：让 Agent 连续选择多个工具

## 1. 本篇要接通的真实能力

第 48–50 篇的 Agent 只有 `choose -> resolve` 两站，一次最多执行一个工具。参考项目的 Agent 可以在同一问题中先查今日回顾，再查相关笔记，最后提出创建笔记。本篇把工作流扩展成有上限的工具循环，并补上时间、用户信息、相关笔记三个工具。技术路线见 [Q25](technology-routes/Q25-agent-tools-and-permissions.md)。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 文件 | 职责 |
|---:|---|---|---|
| 1 | 【修改】 | backend/app/agent/tool_schemas.py | 扩展工具白名单与参数 |
| 2 | 【修改】 | backend/app/agent/tools.py | 新增只读工具 |
| 3 | 【修改】 | backend/app/prompt/tool_choice.txt | 允许根据已执行结果继续选工具 |
| 4 | 【修改】 | backend/app/agent/workflow.py | 循环、观察和最大步数 |
| 5 | 【新增文件】 | backend/tests/test_agent_loop.py | 连续调用与停止条件回归 |
| 6 | 【运行验证】 | 两步工具问题 | 验证连续结果和审批中断 |

## 3. 按顺序修改文件与验证

### 步骤 1：【修改】backend/app/agent/tool_schemas.py

**编辑文件的完整地址：**

~~~text
./backend/app/agent/tool_schemas.py
~~~

**修改定位与前后对照：** 扩展 `ToolName`，增加相关笔记参数。

~~~diff
 ToolName = Literal[
     "none",
     "search_notes",
     "note_stats",
     "today_reviews",
+    "what_time",
+    "get_user_info",
+    "related_notes",
     "create_note",
     "mark_reviewed",
 ]
@@
 class MarkReviewedArgs(BaseModel):
     note_id: str = Field(min_length=1, max_length=36)
@@
     def strip_note_id(cls, value):
         return value.strip() if isinstance(value, str) else value
+
+
+class RelatedNotesArgs(BaseModel):
+    note_id: str = Field(min_length=1, max_length=36)
~~~

**整体解释：** 白名单从“业务写入与查询”扩展到时间和身份信息，但仍不允许任意函数名。`related_notes` 只接收一个笔记 ID，真正的用户范围由服务端补充，模型不能提交 `user_id`。

### 步骤 2：【修改】backend/app/agent/tools.py

**编辑文件的完整地址：**

~~~text
./backend/app/agent/tools.py
~~~

**修改定位与前后对照：** 增加新工具执行分支和相关参数导入。

~~~diff
+from datetime import datetime
 from fastapi import HTTPException
@@
-from app.agent.tool_schemas import CreateNoteArgs, MarkReviewedArgs, ToolChoice
+from app.agent.tool_schemas import (
+    CreateNoteArgs, MarkReviewedArgs, RelatedNotesArgs, ToolChoice,
+)
+from app.rag.related import related_fragments
@@
     if choice.tool == "today_reviews":
         today = await review_service.today(db, user_id)
         return "\n".join(
             f"{item.note_id} | {item.title}" for item in today.reviews
         ) or "今日没有待回顾笔记"
+    if choice.tool == "what_time":
+        return datetime.now().strftime("当前本地时间：%Y-%m-%d %H:%M")
+    if choice.tool == "get_user_info":
+        return f"当前用户 ID：{user_id}"
+    if choice.tool == "related_notes":
+        args = RelatedNotesArgs.model_validate(choice.arguments)
+        items = await related_fragments(db, user_id, args.note_id)
+        return "\n".join(
+            f"{item['id']} | {item['title']} | {item['similarity']}"
+            for item in items
+        ) or "没有找到相关笔记"
     return None
~~~

**整体解释：** 新工具继续复用现有服务。身份工具只返回服务端已经确认的用户 ID，不要求模型解析 JWT；相关笔记工具先通过 `related_fragments` 验证起始笔记归属，不会因为模型给了别人的 note_id 就返回内容。

### 步骤 3：【修改】backend/app/prompt/tool_choice.txt

**编辑文件的完整地址：**

~~~text
./backend/app/prompt/tool_choice.txt
~~~

**修改定位与前后对照：** 增加新工具与“根据已执行结果继续决策”。

~~~diff
-允许的工具：none、search_notes、note_stats、today_reviews、create_note、mark_reviewed。
+允许的工具：none、search_notes、note_stats、today_reviews、what_time、
+get_user_info、related_notes、create_note、mark_reviewed。
 查询统计用 note_stats；查笔记用 search_notes，arguments 中放 query；
 查看今日回顾用 today_reviews；明确要求创建笔记时才选 create_note，参数 title、content；
 明确要求完成某个笔记回顾时才选 mark_reviewed，参数 note_id。
+询问当前时间用 what_time；询问自己的身份用 get_user_info；
+已知 note_id 并要求相关笔记时用 related_notes。
+如果已执行结果还不足以完成用户请求，可以继续选择下一个工具；完成时选 none。
 不确定时选 none。你只是提出调用建议，不能宣称已经执行。
~~~

**整体解释：** 模型现在收到两层输入：用户问题，以及本轮已经执行过的工具结果。它可以先查回顾再创建总结，但每次只能提出一个工具，真正的循环和次数上限由程序控制。

### 步骤 4：【修改】backend/app/agent/workflow.py

**编辑文件的完整地址：**

~~~text
./backend/app/agent/workflow.py
~~~

**修改定位与前后对照：** 用 `choose -> resolve -> observe` 循环替换两节点直线。

~~~diff
 class AgentState(TypedDict, total=False):
     user_id: str
     query: str
     choice: dict
     tool_result: str | None
     proposal: dict | None
+    observations: list[dict]
+    iterations: int
@@
 async def choose(state: AgentState) -> dict:
+    history = json.dumps(
+        state.get("observations", []), ensure_ascii=False,
+    )[-5000:]
     raw = await deepseek_client.chat([
         {"role": "system", "content": PROMPT.read_text(encoding="utf-8")},
-        {"role": "user", "content": state["query"][:2000]},
+        {"role": "user", "content": (
+            f"用户问题：{state['query'][:2000]}\n"
+            f"已执行工具结果：{history or '无'}"
+        )},
     ], json_mode=True, max_tokens=240)
@@
 async def resolve(state: AgentState) -> dict:
@@
     return {"proposal": None, "tool_result": result}
+
+
+async def observe(state: AgentState) -> dict:
+    choice = ToolChoice.model_validate(state["choice"])
+    observations = [
+        *state.get("observations", []),
+        {
+            "tool": choice.tool,
+            "arguments": choice.arguments,
+            "result": state.get("tool_result"),
+        },
+    ][-5:]
+    return {
+        "observations": observations,
+        "iterations": state.get("iterations", 0) + 1,
+    }
+
+
+def should_continue(state: AgentState) -> str:
+    choice = ToolChoice.model_validate(state["choice"])
+    if state.get("proposal"):
+        return "end"
+    if choice.tool in {"none", "create_note", "mark_reviewed"}:
+        return "end"
+    if state.get("iterations", 0) >= 5:
+        return "end"
+    return "choose"
@@
 builder = StateGraph(AgentState)
 builder.add_node("choose", choose)
 builder.add_node("resolve", resolve)
+builder.add_node("observe", observe)
 builder.add_edge(START, "choose")
 builder.add_edge("choose", "resolve")
-builder.add_edge("resolve", END)
+builder.add_edge("resolve", "observe")
+builder.add_conditional_edges(
+    "observe", should_continue, {"choose": "choose", "end": END},
+)
 agent_workflow = builder.compile()
~~~

**整体解释：** `observe` 把上一工具名、参数和结果追加到状态，`choose` 下一次能看到它。条件边是循环闸门：写入提案结束、`none` 结束、或达到 5 次结束。这个上限既防无限工具调用，也控制延迟和费用；截断历史和结果只是控制模型上下文，不改变服务端真实执行记录。

### 步骤 5：【新增文件】backend/tests/test_agent_loop.py

**编辑文件的完整地址：**

~~~text
./backend/tests/test_agent_loop.py
~~~

**完整文件内容：**

~~~python
"""多工具循环与停止条件。"""
import json
import unittest
from unittest.mock import AsyncMock, patch

from app.agent.workflow import agent_workflow


class AgentLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_executes_two_tools_then_stops(self):
        replies = iter([
            json.dumps({"tool": "today_reviews", "arguments": {}}),
            json.dumps({"tool": "none", "arguments": {}}),
        ])
        chat = AsyncMock(side_effect=lambda *args, **kwargs: next(replies))
        read_tool = AsyncMock(side_effect=["1 | 回顾 A", None])

        with patch("app.agent.workflow.deepseek_client.chat", chat), \
             patch("app.agent.workflow.read_tool", read_tool):
            state = await agent_workflow.ainvoke({
                "user_id": "user-1",
                "query": "看看今日回顾",
            })

        self.assertEqual(len(state["observations"]), 2)
        self.assertEqual(state["observations"][0]["tool"], "today_reviews")
        self.assertEqual(state["iterations"], 2)

    async def test_write_proposal_stops_loop(self):
        chat = AsyncMock(return_value=json.dumps({
            "tool": "create_note",
            "arguments": {"title": "总结", "content": "正文"},
        }))
        with patch("app.agent.workflow.deepseek_client.chat", chat):
            state = await agent_workflow.ainvoke({
                "user_id": "user-1",
                "query": "创建总结笔记",
            })

        self.assertEqual(state["proposal"]["tool"], "create_note")
        self.assertEqual(state["iterations"], 1)
~~~

**整体解释：** 测试用两次模型回复驱动循环，再用 `none` 结束。断言不仅检查“有工具结果”，还检查观察列表确实积累了两步。写入路径则必须在第一次提案后停止，不能继续由模型自行选择执行。

### 步骤 6：【运行验证】连续工具与审批

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv run python -m unittest tests.test_agent_loop -v
~~~

在聊天中依次请求“今天有哪些回顾”和“帮我创建一篇总结笔记”。检查 SSE thinking 中是否出现连续工具调用；创建提案必须停在审批，不能自动写库。使用一个没有相关笔记的 ID 调 `related_notes`，应返回空说明而不是报服务器错误。

