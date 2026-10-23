"""原生 Chat Completions 工具契约；身份不由模型传入。"""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.agent.tool_schemas import (
    CreateNoteArgs,
    MarkReviewedArgs,
    RelatedNotesArgs,
    RememberArgs,
    SkillArgs,
)


class EmptyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchArgs(EmptyArgs):
    query: str = Field(min_length=1, max_length=100)


class RagArgs(EmptyArgs):
    query: str = Field(min_length=1, max_length=2000)


class ArtifactArgs(EmptyArgs):
    artifact_id: str = Field(min_length=36, max_length=36)
    offset: int = Field(default=0, ge=0)


class CreateArgs(CreateNoteArgs):
    model_config = ConfigDict(extra="forbid")


class ReviewArgs(MarkReviewedArgs):
    model_config = ConfigDict(extra="forbid")


class RelatedArgs(RelatedNotesArgs):
    model_config = ConfigDict(extra="forbid")


REGISTRY = {
    "search_notes": (SearchArgs, "搜索当前用户笔记，返回摘要与 ID"),
    "note_stats": (EmptyArgs, "查询当前用户的笔记分类统计"),
    "today_reviews": (EmptyArgs, "查询当前用户今日回顾"),
    "what_time": (EmptyArgs, "读取服务器当前时间，不查询实时新闻"),
    "get_user_info": (EmptyArgs, "读取当前用户身份"),
    "related_notes": (RelatedArgs, "根据真实 note_id 查询相关笔记"),
    "create_note": (CreateArgs, "申请创建笔记，必须等待人工审批"),
    "mark_reviewed": (ReviewArgs, "申请完成回顾，必须等待人工审批"),
    "remember": (RememberArgs, "申请写入一条长期记忆，必须等待人工审批"),
    "load_skill": (SkillArgs, "按名称读取技能说明，只读"),
    "search_rag": (RagArgs, "检索本地知识和已配置的外部来源；可换新角度补查"),
    "read_artifact": (ArtifactArgs, "分页读取本会话归档原文，每页最多 2000 字符"),
    "compact": (EmptyArgs, "将旧轮次压缩为摘要，保留最近完整轮次"),
}
TOOLS = [{"type": "function", "function": {
    "name": name, "description": description,
    "parameters": schema.model_json_schema(),
}} for name, (schema, description) in REGISTRY.items()]


class ContextLimitError(RuntimeError):
    """供应商明确拒绝过长上下文；仅允许一次压缩重试。"""


class FunctionCall(BaseModel):
    name: str
    arguments: str


class ToolCall(BaseModel):
    id: str = Field(min_length=1)
    type: Literal["function"]
    function: FunctionCall


class AssistantTurn(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list, max_length=1)

    def message(self) -> dict:
        result = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            result["tool_calls"] = [call.model_dump() for call in self.tool_calls]
        return result
