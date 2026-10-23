"""一次聊天请求内的受控工具决策流。"""

import json
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.agent.checkpoint.factory import get_checkpointer
from app.agent.tool_schemas import ToolChoice
from app.agent.tools import read_tool, write_proposal
from app.db.db_config import AsyncSessionLocal
from app.services.deepseek_client import deepseek_client

PROMPT = Path(__file__).resolve().parents[1] / "prompt" / "tool_choice.txt"


class AgentState(TypedDict, total=False):
    user_id: str
    query: str
    conversation: list[dict[str, str]]
    choice: dict
    tool_result: str | None
    proposal: dict | None
    observations: list[dict]
    iterations: int


async def choose(state: AgentState) -> dict:
    history = json.dumps(
        state.get("observations", []), ensure_ascii=False,
    )[-5000:]
    raw = await deepseek_client.chat([
        {"role": "system", "content": PROMPT.read_text(encoding="utf-8")},
        *state.get("conversation", []),
        {
            "role": "user",
            "content": (
                f"用户问题：{state['query'][:2000]}\n"
                f"已执行工具结果：{history or '无'}\n\n"
                "当前任务是选择工具，不是回答上面的用户问题。"
                "只输出包含 tool 和 arguments 的 JSON 对象；"
                '不需要工具时必须输出 {"tool":"none","arguments":{}}，不能输出空白。'
            ),
        },
    ], json_mode=True, max_tokens=240)
    choice = ToolChoice.model_validate(json.loads(raw))
    return {"choice": choice.model_dump()}


async def resolve(state: AgentState) -> dict:
    choice = ToolChoice.model_validate(state["choice"])
    # 【新增】停止决策不覆盖此前查到的结果。
    if choice.tool == "none":
        return {"proposal": None, "tool_result": state.get("tool_result")}
    proposal = write_proposal(choice)
    if proposal is not None:
        return {"proposal": proposal, "tool_result": None}
    async with AsyncSessionLocal() as db:
        result = await read_tool(db, state["user_id"], choice)
    return {"proposal": None, "tool_result": result}


async def observe(state: AgentState) -> dict:
    choice = ToolChoice.model_validate(state["choice"])
    if choice.tool == "none":
        return {"iterations": state.get("iterations", 0) + 1}
    observations = [
        *state.get("observations", []),
        {
            "tool": choice.tool,
            "arguments": choice.arguments,
            "result": state.get("tool_result"),
        },
    ][-5:]
    return {
        "observations": observations,
        "iterations": state.get("iterations", 0) + 1,
    }


def should_continue(state: AgentState) -> str:
    choice = ToolChoice.model_validate(state["choice"])
    if state.get("proposal"):
        return "end"
    if choice.tool in {"none", "create_note", "mark_reviewed"}:
        return "end"
    if state.get("iterations", 0) >= 5:
        return "end"
    return "choose"


builder = StateGraph(AgentState)
builder.add_node("choose", choose)
builder.add_node("resolve", resolve)
builder.add_node("observe", observe)
builder.add_edge(START, "choose")
builder.add_edge("choose", "resolve")
builder.add_edge("resolve", "observe")
builder.add_conditional_edges(
    "observe", should_continue, {"choose": "choose", "end": END},
)


def build_agent_workflow(checkpointer=None):
    return builder.compile(checkpointer=checkpointer)


agent_workflow = build_agent_workflow(checkpointer=get_checkpointer())
