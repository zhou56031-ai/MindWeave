from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REBUILD_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REBUILD_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "MindWeave"
    ENV: Literal["dev", "test", "prod"] = "dev"

    # 【新增 C01】这里是宿主机访问复刻 MySQL 的配置。
    MYSQL_HOST: str = "127.0.0.1"
    MYSQL_PORT: int = Field(default=13306, ge=1, le=65535)
    MYSQL_USER: str = "rag_learner"
    MYSQL_PASSWORD: SecretStr = SecretStr("mindweave_pass_change_me")
    MYSQL_DATABASE: str = "mindweave"

    # 【新增 C01】JWT 的签名密钥来自本机 .env。
    SECRET_KEY: SecretStr = SecretStr("local_dev_only_change_me")
    ALGORITHM: Literal["HS256"] = "HS256"

    # 【新增 C01】本机复刻 Redis 的宿主机访问参数。
    REDIS_HOST: str = "127.0.0.1"
    REDIS_PORT: int = Field(default=16379, ge=1, le=65535)
    REDIS_DB: int = Field(default=3, ge=0)

    # 【新增】模型凭据只在后端读取；空值允许非 AI 功能独立启动。
    DEEPSEEK_API_KEY: SecretStr = SecretStr("")
    DEEPSEEK_API_KEY_BACKUP: SecretStr = SecretStr("")
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-flash"
    # 【新增】原生工具循环与上下文预算。
    AGENT_MAX_STEPS: int = Field(default=10, ge=1, le=20)
    AGENT_INPUT_BYTES: int = Field(default=60000, ge=20000, le=120000)
    AGENT_OUTPUT_TOKENS: int = Field(default=2048, ge=256, le=4096)

    # 【新增】诊断默认只保存指纹，不保存正文。
    AGENT_TRACE_ENABLED: bool = True
    AGENT_TRACE_INCLUDE_TEXT: bool = False
    AGENT_TRACE_KEEP_DAYS: int = Field(default=7, ge=1, le=30)

    # 【新增】召回、重排与证据预算分别控制。
    RAG_INDEX_BATCH_SIZE: int = Field(default=16, ge=1, le=64)
    RAG_RECALL_LIMIT: int = Field(default=30, ge=10, le=100)
    RAG_RERANK_LIMIT: int = Field(default=20, ge=5, le=40)
    RAG_FINAL_LIMIT: int = Field(default=6, ge=1, le=10)
    RAG_CONTEXT_CHARS: int = Field(default=8000, ge=2000, le=12000)
    # 【新增】双路配额与向量过采样：避免单源挤占，也避免 post-filter 截断。
    RAG_VECTOR_QUOTA: int = Field(default=20, ge=5, le=100)
    RAG_FULLTEXT_QUOTA: int = Field(default=20, ge=5, le=100)
    RAG_VECTOR_OVERFETCH: int = Field(default=1000, ge=100, le=5000)
    # 【新增】只控制最终流式回答，不改变短 JSON 任务的预算。
    CHAT_ANSWER_MAX_TOKENS: int = Field(default=2048, ge=256, le=4096)

    # 【新增】空 URI 允许非图功能独立启动。
    NEO4J_URI: str = ""
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: SecretStr = SecretStr("")

    # 【新增】模型名和维度共同定义 Neo4j 向量索引契约。
    EMBEDDING_PROVIDER: Literal["local", "remote"] = "local"
    EMBEDDING_MODEL: str = "BAAI/bge-small-zh-v1.5"
    EMBEDDING_DIMENSIONS: int = Field(default=512, ge=1, le=4096)
    EMBEDDING_BASE_URL: str = "https://maas.qianwenaiapi.com/compatible-mode/v1"
    EMBEDDING_API_KEY: SecretStr = SecretStr("")
    EMBEDDING_BATCH_SIZE: int = Field(default=10, ge=1, le=10)
    # 【新增】查询向量缓存与全文分析器，减少重复计费/改善中文召回。
    EMBEDDING_CACHE_ENABLED: bool = True
    EMBEDDING_CACHE_TTL: int = Field(default=604800, ge=60, le=2592000)
    RAG_FULLTEXT_ANALYZER: str = "cjk"

    VISION_BATCH_SIZE: int = Field(default=5, ge=1, le=10)
    VISION_DEDUP_ENABLED: bool = True
    VISION_DEDUP_THRESHOLD: int = Field(default=10, ge=0, le=64)
    VISION_MAX_PAGES: int = Field(default=50, ge=1, le=200)

    WEB_SEARCH_ENABLED: bool = False
    WEB_SEARCH_PROVIDER: str = ""
    WEB_SEARCH_API_KEY: SecretStr = SecretStr("")

    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_CHAT_PER_MINUTE: int = Field(default=10, ge=1, le=1000)
    RATE_LIMIT_UPLOAD_PER_MINUTE: int = Field(default=5, ge=1, le=1000)
    LOG_LEVEL: str = "INFO"


settings = Settings()
