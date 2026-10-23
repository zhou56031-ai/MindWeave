"""模型抽取结果的结构边界。"""
from pydantic import BaseModel, Field, model_validator


class ExtractedEntity(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: str = Field(default="concept", max_length=50)
    description: str = Field(default="", max_length=500)


class ExtractedRelation(BaseModel):
    source: str
    target: str
    relation_type: str = Field(min_length=1, max_length=50)


class ExtractResult(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list, max_length=30)
    relations: list[ExtractedRelation] = Field(default_factory=list, max_length=60)

    @model_validator(mode="after")
    def links_use_known_entities(self):
        names = [entity.name.strip() for entity in self.entities]
        # 图存储会把名称 casefold 后生成实体 ID，校验必须使用同一规范。
        canonical_names = [name.casefold() for name in names]
        if len(canonical_names) != len(set(canonical_names)):
            raise ValueError("实体名称不能重复")
        if any(not name for name in names):
            raise ValueError("实体名称不能为空")
        known = set(names)
        if any(link.source not in known or link.target not in known
               for link in self.relations):
            raise ValueError("关系两端必须在实体清单中")
        return self
