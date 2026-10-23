# 第 49 篇：LangGraph 决策流与待审批运行记录

## 1. 本篇要接通的真实能力

前一篇有了工具白名单，但还缺一条可重复的流程把“选择工具—执行只读工具或生成写入提案”串起来。本篇用 LangGraph 的 StateGraph 固定这个顺序，并用 MySQL 保存将来可能跨浏览器恢复的运行记录。LangGraph 在本篇只负责一次请求内的节点编排；跨重启恢复依赖 MySQL 的 AgentRun，而不是进程内的 MemorySaver。为何这样选以及和原生 LangGraph checkpointer 的取舍见 [Q26](technology-routes/Q26-langgraph-and-durable-state.md)。

本篇**不会**把写入提案直接执行。第 50 篇才把提案接入前端审批卡和恢复接口。模型只选择工具，服务端仍检查工具名、参数和 JWT 用户身份。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 文件 | 职责 |
|---:|---|---|---|
| 1 | 【新增依赖】 | backend/pyproject.toml、backend/requirements.txt | 安装 LangGraph |
| 2 | 【新增文件】 | backend/app/models/agent_run.py | 持久化审批运行状态 |
| 3 | 【修改】 | backend/app/db/db_config.py | 注册新表 |
| 4 | 【新增文件】 | backend/app/agent/workflow.py | 固定选择、读取、提案的节点顺序 |
| 5 | 【运行验证】 | 编译、建表与模拟模型返回 | 确认流程不自动写入 |

运行记录字段中的 proposal 是服务端验证后的内容，不接受浏览器传入的任意工具名。请先做完第 48 篇，再开始本篇。

## 3. 按顺序修改文件与验证

### 步骤 1：【新增依赖】安装 LangGraph

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv add langgraph
uv export --locked --no-dev --no-emit-project --no-hashes --format requirements.txt --output-file requirements.txt
~~~

**整体解释：** uv 同时更新依赖声明和锁文件。requirements.txt 是给按传统 pip 流程部署时使用的导出副本，不要手写两个不同版本。这里使用 StateGraph 的稳定核心接口；具体安装版本以本机锁文件为准。

### 步骤 2：【新增文件】backend/app/models/agent_run.py

**编辑文件的完整地址：**

~~~text
./backend/app/models/agent_run.py
~~~

**完整文件内容：**

~~~python
"""一次工具审批运行的持久记录。"""
from sqlalchemy import Column, DateTime, ForeignKey, JSON, String, Text, func

from app.models.base import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(String(36), primary_key=True)
    session_id = Column(
        String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    user_id = Column(String(36), index=True, nullable=False)
    status = Column(String(20), default="pending", nullable=False)
    query = Column(Text, nullable=False)
    proposal = Column(JSON, nullable=False)
    result = Column(Text, nullable=True)
    created_at = Column(DateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )
~~~

**整体解释：** ChatSession 是谈话文件夹，AgentRun 是夹在里面的一张“待签字申请单”。session_id 把两者绑起来；user_id 让查询必须在当前账号范围内；status 区分 pending、executing、completed、rejected。proposal 是经过 ToolChoice 和参数模型检查后的快照，审批页展示的和后台准备执行的应是同一份。这里不保存令牌或模型 API 密钥。

### 步骤 3：【修改】backend/app/db/db_config.py

**编辑文件的完整地址：**

~~~text
./backend/app/db/db_config.py
~~~

**修改定位与前后对照：** 在 init_db 内现有 ChatSession、ChatMessage 导入后增加一行；不能只创建模型文件而忘记注册。

~~~diff
     from app.models.chat_history import ChatSession, ChatMessage  # noqa: F401
+    from app.models.agent_run import AgentRun  # noqa: F401
~~~

**整体解释：** SQLAlchemy 的 Base.metadata 像一张已登记的建表清单。导入 AgentRun 时，agent_runs 表才进入清单；启动时的 create_all 只创建缺失的表，不负责修改已有表结构。第 50 篇会使用这张表保存等待审批的状态。

### 步骤 4：【新增文件】backend/app/agent/workflow.py

**编辑文件的完整地址：**

~~~text
./backend/app/agent/workflow.py
~~~

**完整文件内容：**

~~~python
"""一次聊天请求内的受控工具决策流。"""
import json
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.agent.tool_schemas import ToolChoice
from app.agent.tools import read_tool, write_proposal
from app.db.db_config import AsyncSessionLocal
from app.services.deepseek_client import deepseek_client

PROMPT = Path(__file__).resolve().parents[1] / "prompt" / "tool_choice.txt"


class AgentState(TypedDict, total=False):
    user_id: str
    query: str
    choice: dict
    tool_result: str | None
    proposal: dict | None


async def choose(state: AgentState) -> dict:
    raw = await deepseek_client.chat([
        {"role": "system", "content": PROMPT.read_text(encoding="utf-8")},
        {"role": "user", "content": state["query"][:2000]},
    ], json_mode=True, max_tokens=240)
    choice = ToolChoice.model_validate(json.loads(raw))
    return {"choice": choice.model_dump()}


async def resolve(state: AgentState) -> dict:
    choice = ToolChoice.model_validate(state["choice"])
    proposal = write_proposal(choice)
    if proposal is not None:
        return {"proposal": proposal, "tool_result": None}
    async with AsyncSessionLocal() as db:
        result = await read_tool(db, state["user_id"], choice)
    return {"proposal": None, "tool_result": result}


builder = StateGraph(AgentState)
builder.add_node("choose", choose)
builder.add_node("resolve", resolve)
builder.add_edge(START, "choose")
builder.add_edge("choose", "resolve")
builder.add_edge("resolve", END)
agent_workflow = builder.compile()
~~~

**整体解释：** 可以把图想成两站式传送带。第一站只读取用户问题，请 DeepSeek 从白名单里写一张建议单；第二站由 Python 核验这张单：读操作在当前用户的数据库会话中执行，写操作只产生 proposal。StateGraph 的 state 是两站之间的信封，不能把浏览器传来的 user_id 塞进去；调用方必须传 JWT 依赖得到的 user_id。编译后的图没有持久 checkpointer，所以运行结束就不依赖它记住状态；跨请求审批由 AgentRun 承担。

### 步骤 5：【运行验证】确认“提案不等于执行”

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv run python -m compileall -q app main.py
uv run python -c "from app.agent.workflow import agent_workflow; print(agent_workflow.get_graph().draw_mermaid())"
~~~

启动后端后确认 MySQL 新增 agent_runs 表。用模拟 DeepSeek 响应分别选择 none、search_notes、create_note：前两者只有只读结果；create_note 只有 proposal，notes 表行数不变。若模型给出不在白名单的名字，ToolChoice 应拒绝，不能执行。检查完再进入第 50 篇的审批恢复。
