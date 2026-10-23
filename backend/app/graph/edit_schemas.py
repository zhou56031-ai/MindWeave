"""图编辑请求不接受客户端 user_id。"""

from pydantic import BaseModel, Field, field_validator


class EntityIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    display_name: str | None = Field(default=None, max_length=120)
    type_id: str | None = None
    description: str | None = Field(default=None, max_length=500)
    aliases: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("name", "display_name", mode="before")
    @classmethod
    def strip_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("aliases")
    @classmethod
    def clean_aliases(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if any(len(value) > 120 for value in cleaned):
            raise ValueError("别名不能超过 120 字符")
        return list(dict.fromkeys(cleaned))


class TypeIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    display_name: str = Field(min_length=1, max_length=50)
    color: str = Field(default="#888888", pattern=r"^#[0-9a-fA-F]{6}$")
    icon: str | None = Field(default=None, max_length=100)

    @field_validator("name", "display_name", mode="before")
    @classmethod
    def strip_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class RelationIn(BaseModel):
    source_id: str = Field(min_length=1, max_length=36)
    target_id: str = Field(min_length=1, max_length=36)
    relation_type: str = Field(min_length=1, max_length=50)

    @field_validator("relation_type", mode="before")
    @classmethod
    def strip_relation_type(cls, value):
        return value.strip() if isinstance(value, str) else value


class MergeIn(BaseModel):
    target_id: str = Field(min_length=1, max_length=36)
    source_id: str = Field(min_length=1, max_length=36)
