from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class NoteCreate(BaseModel):
    # 【新增】先处理首尾空白，再检查标题长度。
    title: str = Field(min_length=1, max_length=200)
    content: str
    category: str | None = Field(default=None, max_length=50)
    tags: list[str] | None = None

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value):
        return value.strip() if isinstance(value, str) else value
class NoteResponse(BaseModel):
    # 【新增 C01】允许从 ORM 对象属性读取响应字段。
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    title: str
    content: str
    tags: list[str] | None = None
    category: str | None = None
    is_pinned: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class NoteListResponse(BaseModel):
    notes: list[NoteResponse]
    total_count: int


class NoteUpdate(BaseModel):
    # 【新增 C01】所有字段可省略，但明确传 null 有单独约定。
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = None
    category: str | None = Field(default=None, max_length=50)
    tags: list[str] | None = None
    is_pinned: bool | None = None

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def reject_null_for_required_columns(self):
        for name in ("title", "content", "is_pinned"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} 不能显式设为 null")
        return self


class NoteTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    name: str
    icon: str
    category: str
    title: str
    content: str
    tags: list[str]
    is_default: bool
    sort_order: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class NoteTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    icon: str = Field(default="FileText", max_length=50)
    category: str = Field(default="", max_length=50)
    title: str = Field(default="", max_length=200)
    content: str = ""
    tags: list[str] = Field(default_factory=list)


class NoteTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    icon: str | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, max_length=50)
    title: str | None = Field(default=None, max_length=200)
    content: str | None = None
    tags: list[str] | None = None


class NoteTemplateReorder(BaseModel):
    ids: list[str] = Field(min_length=1)


class BatchIdsRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("ids")
    @classmethod
    def no_duplicate_ids(cls, ids: list[str]) -> list[str]:
        if len(ids) != len(set(ids)):
            raise ValueError("笔记 ID 不能重复")
        return ids


class BatchPinRequest(BatchIdsRequest):
    is_pinned: bool


class BatchCategoryRequest(BatchIdsRequest):
    category: str = Field(max_length=50)


class KnowledgeDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    user_id: str
    md5: str
    file_size: int
    file_type: str = ""
    status: str
    chunk_count: int
    preview: str = ""
    created_at: datetime


class KnowledgeListResponse(BaseModel):
    documents: list[KnowledgeDocumentResponse]
    total_count: int


class KnowledgeChunkResponse(BaseModel):
    chunk_id: str
    index: int
    content: str
    page: int | None = None
    images: list[str] = Field(default_factory=list)


class KnowledgeDocumentDetail(BaseModel):
    id: str
    filename: str
    user_id: str
    md5: str
    chunk_count: int
    content: str
    chunks: list[KnowledgeChunkResponse]
    images: list[str] = Field(default_factory=list)
    created_at: datetime


class DocumentChunksResponse(BaseModel):
    filename: str
    total_chunks: int
    chunks: list[KnowledgeChunkResponse]


class MD5Record(BaseModel):
    md5: str
    filename: str
    original_filename: str
    upload_time: str


class MD5ListResponse(BaseModel):
    records: list[MD5Record]
    total_count: int


class ReviewItemResponse(BaseModel):
    review_id: str
    note_id: str
    title: str
    content_preview: str
    tags: list[str] = Field(default_factory=list)
    category: str = ""
    review_count: int
    last_reviewed_at: datetime | None = None
    interval_days: int


class ReviewTodayResponse(BaseModel):
    reviews: list[ReviewItemResponse]
    total_count: int


class ReviewDoneResponse(BaseModel):
    success: bool
    message: str
    review_count: int
    interval_days: int
    next_review_at: datetime


class ReviewQuestionResponse(BaseModel):
    question: str = Field(min_length=5, max_length=500)
    choices: list[str] = Field(min_length=4, max_length=4)
    answer: str

    @model_validator(mode="after")
    def check_options(self):
        cleaned = [choice.strip() for choice in self.choices]
        if any(not choice for choice in cleaned) or len(set(cleaned)) != 4:
            raise ValueError("选项必须是四个不同的非空字符串")
        if self.answer not in cleaned:
            raise ValueError("答案必须来自选项")
        self.choices = cleaned
        return self


class AutocompleteRequest(BaseModel):
    context: str = Field(min_length=1, max_length=2000)

    @field_validator("context", mode="before")
    @classmethod
    def trim_context(cls, value):
        return value.strip() if isinstance(value, str) else value


class AutocompleteResponse(BaseModel):
    completion: str


class AutoTagResponse(BaseModel):
    note_id: str
    tags: list[str]


class ChatSessionResponse(BaseModel):
    id: str
    user_id: str
    title: str
    metadata: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    pending_run_id: str | None = None


class ChatMessageResponse(BaseModel):
    id: int
    session_id: str
    role: str
    content: str
    metadata: dict = Field(default_factory=dict)
    created_at: datetime


class ChatSessionDetail(BaseModel):
    session_id: str
    history: list[tuple[str, str]]
    pending_run_id: str | None = None


class RetrievalHit(BaseModel):
    source_kind: str
    source_id: str
    title: str
    snippet: str
    score: int = Field(ge=1)
    # 【新增】定位到具体片段；来源 ID 仍保持原业务记录 ID。
    chunk_id: str | None = None
    chunk_index: int | None = None
    page: int | None = None
    section: str | None = None
    parent_text: str | None = None
    url: str | None = None
    rerank_score: int | None = Field(default=None, ge=0, le=3)


class ChatQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, max_length=36)

    @field_validator("query", mode="before")
    @classmethod
    def normalize_query_text(cls, value):
        return value.strip() if isinstance(value, str) else value
