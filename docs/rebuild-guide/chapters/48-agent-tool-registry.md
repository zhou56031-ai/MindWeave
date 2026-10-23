# 第 48 篇：Agent 工具白名单与用户身份边界

## 1. 本篇要接通的真实能力

聊天回答不只复述资料，参考项目还可查询笔记统计、今日回顾，或提出创建笔记和完成回顾。本篇先把这些动作集中成**工具白名单**：模型只能建议工具名和参数，服务端以 JWT 用户 ID 执行；写入动作暂时只形成待审批提案，第 50 篇才允许真正执行。这样“模型说要创建笔记”不等于已经写库。工具选型和同类编排方案见 [Q25](technology-routes/Q25-agent-tools-and-permissions.md)。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 文件 | 职责 |
|---:|---|---|---|
| 1 | 【新增文件】 | backend/app/agent/__init__.py | Agent 包 |
| 2 | 【新增文件】 | backend/app/agent/tool_schemas.py | 工具名和参数契约 |
| 3 | 【新增文件】 | backend/app/agent/tools.py | 只读执行与写入提案 |
| 4 | 【新增文件】 | backend/app/prompt/tool_choice.txt | 模型选择工具的受限任务 |

本篇不把令牌原文交给模型；也不允许模型自行写 SQL、读任意文件或调用任何不在列表中的函数。

## 3. 按顺序修改文件与验证

### 步骤 1：【新增文件】backend/app/agent/__init__.py

**编辑文件的完整地址：**

~~~text
./backend/app/agent/__init__.py
~~~

**完整文件内容：**

~~~python
"""受控 Agent 工具与工作流。"""
~~~

### 步骤 2：【新增文件】backend/app/agent/tool_schemas.py

**编辑文件的完整地址：**

~~~text
./backend/app/agent/tool_schemas.py
~~~

**完整文件内容：**

~~~python
"""模型建议的工具调用，服务端再次校验。"""
from typing import Literal
from pydantic import BaseModel, Field


ToolName = Literal["none", "search_notes", "note_stats", "today_reviews",
                   "create_note", "mark_reviewed"]


class ToolChoice(BaseModel):
    tool: ToolName
    arguments: dict = Field(default_factory=dict)


class CreateNoteArgs(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(default="", max_length=10000)


class MarkReviewedArgs(BaseModel):
    note_id: str = Field(min_length=1, max_length=36)
~~~

**整体解释：** 模型输出的 JSON 只是建议单，Pydantic 把不在白名单中的工具名挡掉。每个写入工具还有专属参数模型；不能把任意 dict 直接传给服务。客户端 user_id、role、SQL 都不在参数中，避免模型或浏览器伪造身份。

### 步骤 3：【新增文件】backend/app/agent/tools.py

**编辑文件的完整地址：**

~~~text
./backend/app/agent/tools.py
~~~

**完整文件内容：**

~~~python
"""把工具名映射到当前用户的业务服务。"""
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tool_schemas import CreateNoteArgs, MarkReviewedArgs, ToolChoice
from app.services.note_service import note_service
from app.services.review_service import review_service


async def read_tool(
    db: AsyncSession, user_id: str, choice: ToolChoice
) -> str | None:
    if choice.tool == "none":
        return None
    if choice.tool == "search_notes":
        query = str(choice.arguments.get("query", "")).strip()[:100]
        if not query:
            raise HTTPException(status_code=422, detail="搜索词为空")
        notes, _ = await note_service.search_notes(db, user_id, query, 1, 5)
        return "\n".join(f"{note.id} | {note.title} | {note.content[:200]}"
                         for note in notes) or "没有找到笔记"
    if choice.tool == "note_stats":
        stats = await note_service.get_category_stats(db, user_id)
        return str(stats)
    if choice.tool == "today_reviews":
        today = await review_service.today(db, user_id)
        return "\n".join(f"{item.note_id} | {item.title}" for item in today.reviews) or "今日没有待回顾笔记"
    return None


def write_proposal(choice: ToolChoice) -> dict | None:
    if choice.tool == "create_note":
        args = CreateNoteArgs.model_validate(choice.arguments)
        return {"tool": "create_note", "arguments": args.model_dump(),
                "description": f"创建笔记：{args.title}"}
    if choice.tool == "mark_reviewed":
        args = MarkReviewedArgs.model_validate(choice.arguments)
        return {"tool": "mark_reviewed", "arguments": args.model_dump(),
                "description": f"标记回顾：{args.note_id}"}
    return None


async def execute_approved_write(
    db: AsyncSession, user_id: str, proposal: dict
) -> str:
    if proposal["tool"] == "create_note":
        args = CreateNoteArgs.model_validate(proposal["arguments"])
        from app.schemas.models import NoteCreate
        note = await note_service.create_note(
            db, user_id, NoteCreate(title=args.title, content=args.content)
        )
        return f"已创建笔记 {note.title}，ID {note.id}"
    if proposal["tool"] == "mark_reviewed":
        args = MarkReviewedArgs.model_validate(proposal["arguments"])
        result = await review_service.mark_done(db, user_id, args.note_id)
        return f"已完成第 {result.review_count} 次回顾"
    raise HTTPException(status_code=422, detail="未知写入工具")
~~~

**整体解释：** 工具执行时永远由路由传入当前 JWT 用户 ID，并复用已经实现的 NoteService 和 ReviewService，因此原有用户隔离、事务与间隔规则不会被 Agent 绕开。read_tool 只返回必要摘要；写入先产生可阅读提案，execute_approved_write 不在本篇自动调用。第 50 篇恢复审批时会重新验证提案和归属，避免“审批时看到 A，执行时却用 B 参数”。

### 步骤 4：【新增文件】backend/app/prompt/tool_choice.txt

**编辑文件的完整地址：**

~~~text
./backend/app/prompt/tool_choice.txt
~~~

**完整文件内容：**

~~~text
你负责判断用户问题是否需要调用一个工具。只输出 JSON 对象：
{"tool":"none","arguments":{}}
允许的工具：none、search_notes、note_stats、today_reviews、create_note、mark_reviewed。
查询统计用 note_stats；查笔记用 search_notes，arguments 中放 query；
查看今日回顾用 today_reviews；明确要求创建笔记时才选 create_note，参数 title、content；
明确要求完成某个笔记回顾时才选 mark_reviewed，参数 note_id。
不确定时选 none。你只是提出调用建议，不能宣称已经执行。
~~~

**整体解释：** 任务单缩小模型选择范围，但真正权限边界在 Python 白名单与业务服务中。模型若被笔记正文里的“忽略规则”影响，仍不能变出任意工具。写入建议必须有用户明确意图，后面仍需人工审批。

### 步骤 5：【运行验证】白名单与只读工具

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv run python -m compileall -q app main.py
uv run python - <<'PY'
from pydantic import ValidationError
from app.agent.tool_schemas import ToolChoice
try:
    ToolChoice.model_validate({"tool":"delete_everything","arguments":{}})
except ValidationError:
    print("unknown tool rejected")
PY
~~~

用两个账号同一关键词验证 read_tool 只返回当前用户笔记。构造 create_note 提案后查询 MySQL，当前应**没有新增笔记**；若已新增，说明审批边界被提前跨过。
