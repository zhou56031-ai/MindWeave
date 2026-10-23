"""模型建议的工具调用，服务端再次校验。"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

ToolName = Literal[
    "none",
    "search_notes",
    "note_stats",
    "today_reviews",
    "what_time",
    "get_user_info",
    "related_notes",
    "create_note",
    "mark_reviewed",
    "remember",
    "load_skill",
]


class ToolChoice(BaseModel):
    tool: ToolName
    arguments: dict = Field(default_factory=dict)


class CreateNoteArgs(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(default="", max_length=10000)

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, value):
        return value.strip() if isinstance(value, str) else value


class MarkReviewedArgs(BaseModel):
    note_id: str = Field(min_length=1, max_length=36)

    @field_validator("note_id", mode="before")
    @classmethod
    def strip_note_id(cls, value):
        return value.strip() if isinstance(value, str) else value


class RememberArgs(BaseModel):
    content: str = Field(min_length=1, max_length=500)

    @field_validator("content", mode="before")
    @classmethod
    def strip_content(cls, value):
        return value.strip() if isinstance(value, str) else value


class SkillArgs(BaseModel):
    name: str = Field(min_length=1, max_length=41)


class RelatedNotesArgs(BaseModel):
    note_id: str = Field(min_length=1, max_length=36)
