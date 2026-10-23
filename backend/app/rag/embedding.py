"""本地或远程文本向量，统一输出 L2 归一化向量。"""

import asyncio
import hashlib
import json
import math
from functools import lru_cache
from typing import TYPE_CHECKING

import httpx
from fastapi import HTTPException

from app.core.agent_trace import emit
from app.core.settings import settings
from app.db.redis_config import get_redis

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


@lru_cache(maxsize=1)
def model() -> "SentenceTransformer":
    """只有在 provider=local 时才会加载本地模型。"""
    from sentence_transformers import SentenceTransformer

    try:
        return SentenceTransformer(
            settings.EMBEDDING_MODEL,
            local_files_only=True,
        )
    except OSError:
        return SentenceTransformer(settings.EMBEDDING_MODEL)


def _normalize(vector: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        raise RuntimeError("嵌入服务返回零向量")
    return [value / magnitude for value in vector]


def _validate_vector(values: list[float]) -> list[float]:
    if len(values) != settings.EMBEDDING_DIMENSIONS:
        raise RuntimeError("嵌入输出维度与索引配置不一致")
    return _normalize([float(value) for value in values])


async def _remote_embeddings(texts: list[str]) -> list[list[float]]:
    key = settings.EMBEDDING_API_KEY.get_secret_value().strip()
    if not key:
        raise HTTPException(status_code=503, detail="远程嵌入服务未配置")
    if not settings.EMBEDDING_BASE_URL.strip():
        raise HTTPException(status_code=503, detail="远程嵌入地址未配置")

    body = {
        "model": settings.EMBEDDING_MODEL,
        "input": texts,
        "dimensions": settings.EMBEDDING_DIMENSIONS,
        "encoding_format": "float",
    }
    timeout = httpx.Timeout(45.0, connect=5.0, read=40.0, write=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                settings.EMBEDDING_BASE_URL.rstrip("/") + "/embeddings",
                headers={"Authorization": f"Bearer {key}"},
                json=body,
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {401, 403}:
            raise HTTPException(
                status_code=503,
                detail="远程嵌入服务认证失败",
            ) from exc
        raise HTTPException(
            status_code=502,
            detail="远程嵌入服务返回错误",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail="远程嵌入服务暂不可用",
        ) from exc

    try:
        data = response.json()["data"]
        ordered = sorted(data, key=lambda item: int(item["index"]))
        vectors = [
            _validate_vector(item["embedding"])
            for item in ordered
        ]
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=502,
            detail="远程嵌入响应格式异常",
        ) from exc
    if len(vectors) != len(texts):
        raise HTTPException(
            status_code=502,
            detail="远程嵌入返回数量不一致",
        )
    return vectors


async def _local_embeddings(texts: list[str]) -> list[list[float]]:
    def calculate() -> list[list[float]]:
        values = model().encode(texts, normalize_embeddings=True)
        return [_validate_vector(list(value)) for value in values]

    return await asyncio.to_thread(calculate)


async def embed_many(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    if any(not text.strip() for text in texts):
        raise ValueError("嵌入文本不能为空")
    if settings.EMBEDDING_PROVIDER == "local":
        return await _local_embeddings(texts)

    vectors: list[list[float]] = []
    for start in range(0, len(texts), settings.EMBEDDING_BATCH_SIZE):
        vectors.extend(await _remote_embeddings(
            texts[start:start + settings.EMBEDDING_BATCH_SIZE],
        ))
    return vectors


async def embed(text: str) -> list[float]:
    """查询向量走 Redis 缓存；索引批量写入不经过这里，避免污染。"""
    if settings.EMBEDDING_PROVIDER == "local" or not settings.EMBEDDING_CACHE_ENABLED:
        return (await embed_many([text]))[0]
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    key = f"emb:{settings.EMBEDDING_MODEL}:{settings.EMBEDDING_DIMENSIONS}:{digest}"
    try:
        cached = await get_redis().get(key)
    except Exception:
        cached = None
    if cached:
        emit("embedding.cache", hit=True, key=digest[:12])
        return json.loads(cached)
    emit("embedding.cache", hit=False, key=digest[:12])
    vector = (await embed_many([text]))[0]
    try:
        await get_redis().set(key, json.dumps(vector), ex=settings.EMBEDDING_CACHE_TTL)
    except Exception:
        pass
    return vector
