# 第 45 篇：本地/线上 Embedding 与 Neo4j 向量索引

## 1. 本篇要接通的真实能力

第 35 篇只能按字面子串找资料。本篇给笔记和文档切片计算向量，保存到 Neo4j Chunk 节点并建立 512 维余弦索引。代码支持两种 provider：`local` 使用 BAAI/bge-small-zh-v1.5，`remote` 使用 OpenAI 兼容的托管 Embedding API。当前复刻项目采用 QwenCloud `text-embedding-v4` 的 512 维输出，L2 归一化后写图。DeepSeek 仍负责生成回答；Embedding 负责把文字映射成可比较向量。选型与迁移边界见 [Q22](technology-routes/Q22-embedding-vector-index.md)，接口格式见[QwenCloud 文本向量文档](https://platform.qianwenai.com/docs/api-reference/text-embedding/openai-embedding)。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 文件 | 用途 |
|---:|---|---|---|
| 1 | 【安装依赖】 | backend/pyproject.toml、uv.lock、requirements.txt | 本地编码与远程 HTTP |
| 2 | 【修改】 | backend/app/core/settings.py、.env.example、docker-compose.yml | provider、模型、维度与密钥 |
| 3 | 【新增文件】 | backend/app/rag/__init__.py、embedding.py、chunk_index.py | 编码与索引同步 |
| 4 | 【修改】 | backend/app/graph/neo4j_client.py、worker.py | 索引约束与构建 |
| 5 | 【运行验证】 | 模型探针与临时 Chunk | 核对维度和用户范围 |

远程模式不需要下载模型；本地模式第一次运行才可能下载到本机缓存。下载完成与代码编译成功是两件事。切换模型必须重建现有 Chunk 向量。

## 3. 按顺序修改文件与验证

### 步骤 1：【安装依赖】本地编码库与 HTTP 客户端

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv add sentence-transformers
uv add httpx
uv export --locked --no-dev --no-emit-project --no-hashes --format requirements.txt --output-file requirements.txt
~~~

不要为了让索引不报错而截断向量维度；换模型必须重建已有 Chunk 向量。

### 步骤 2：【修改】backend/app/core/settings.py

**编辑文件的完整地址：**

~~~text
./backend/app/core/settings.py
~~~

**修改定位与前后对照：**

~~~diff
     NEO4J_PASSWORD: SecretStr = SecretStr("")
+    EMBEDDING_PROVIDER: Literal["local", "remote"] = "local"
+    EMBEDDING_MODEL: str = "BAAI/bge-small-zh-v1.5"
+    EMBEDDING_DIMENSIONS: int = Field(default=512, ge=1, le=4096)
+    EMBEDDING_BASE_URL: str = "https://maas.qianwenaiapi.com/compatible-mode/v1"
+    EMBEDDING_API_KEY: SecretStr = SecretStr("")
+    EMBEDDING_BATCH_SIZE: int = Field(default=10, ge=1, le=10)
~~~

**整体解释：** 模型名和维度共同构成索引契约，运行时还要实测输出长度。`remote` 通过 OpenAI 兼容 `/embeddings` 访问 QwenCloud；`EMBEDDING_API_KEY` 是 `SecretStr`，只从后端 `.env` 读取。批量上限设为 10，与 `text-embedding-v4` 的接口限制一致。设置值改变不会自动转换旧向量；必须按当前用户来源范围重建。

### 步骤 3：【修改】.env.example

**编辑文件的完整地址：**

~~~text
./.env.example
~~~

**修改定位与前后对照：**

~~~diff
 NEO4J_PASSWORD=
+EMBEDDING_PROVIDER=local
+EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
+EMBEDDING_DIMENSIONS=512
+EMBEDDING_BASE_URL=https://maas.qianwenaiapi.com/compatible-mode/v1
+EMBEDDING_API_KEY=
+EMBEDDING_BATCH_SIZE=10
~~~

实际启用 QwenCloud 时，只在本机 `.env` 设置：

~~~env
EMBEDDING_PROVIDER=remote
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMENSIONS=512
EMBEDDING_BASE_URL=https://maas.qianwenaiapi.com/compatible-mode/v1
EMBEDDING_API_KEY=<你的 QwenCloud API Key>
EMBEDDING_BATCH_SIZE=10
~~~

API Key 不能写进 `.env.example`、前端或 Git。

### 步骤 4：【新增文件】backend/app/rag/__init__.py

**编辑文件的完整地址：**

~~~text
./backend/app/rag/__init__.py
~~~

**完整文件内容：**

~~~python
"""检索与嵌入服务。"""
~~~

### 步骤 5：【新增文件】backend/app/rag/embedding.py

**编辑文件的完整地址：**

~~~text
./backend/app/rag/embedding.py
~~~

**完整文件内容：**

~~~python
"""本地或远程文本向量，统一输出 L2 归一化向量。"""

import asyncio
import math
from functools import lru_cache
from typing import TYPE_CHECKING

import httpx
from fastapi import HTTPException

from app.core.settings import settings

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
    return (await embed_many([text]))[0]
~~~

**整体解释：** `remote` 走 QwenCloud 的 OpenAI 兼容 `/embeddings`，按最多 10 条分批；返回顺序按 `index` 重排，再验证维度和零向量。远程与本地结果都做 L2 归一化，所以后续点积可以直接作为余弦相似度。`sentence_transformers` 放在 `model()` 内部导入，线上模式启动时不会加载 PyTorch；只有切到 `local` 才需要本地模型和内存。

### 步骤 6：【修改】backend/app/graph/neo4j_client.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/neo4j_client.py
~~~

**修改定位与前后对照：** ensure_graph_schema 的建约束循环后加维度检查。下列 Cypher 索引配置键使用反引号，属于代码内容。

~~~diff
@@ async def ensure_graph_schema() -> None:
     for statement in statements:
         await driver.execute_query(statement)
+    rows = (await driver.execute_query(
+        "SHOW VECTOR INDEXES YIELD name, options "
+        "WHERE name = 'chunk_embedding_index' RETURN options"
+    )).records
+    if rows:
+        old = (rows[0]["options"] or {}).get("indexConfig", {}).get("vector.dimensions")
+        if old is not None and int(old) != settings.EMBEDDING_DIMENSIONS:
+            raise RuntimeError("已有向量索引维度不同，必须规划重建")
+    await driver.execute_query(
+        "CREATE VECTOR INDEX chunk_embedding_index IF NOT EXISTS "
+        "FOR (c:Chunk) ON c.embedding "
+        "OPTIONS {indexConfig: {"
+        f"  `vector.dimensions`: {settings.EMBEDDING_DIMENSIONS},"
+        "  `vector.similarity_function`: 'cosine'"
+        "}}",
++    )
~~~

**整体解释：** 索引像固定 512 格的抽屉；IF NOT EXISTS 不会把旧规格改成新规格，所以必须先检查。索引构建可能在后台进行，之后还要确认 ONLINE。这里沿用第 39 篇导入的 settings，不需要重复导入。

### 步骤 7：【新增文件】backend/app/rag/chunk_index.py

**编辑文件的完整地址：**

~~~text
./backend/app/rag/chunk_index.py
~~~

**完整文件内容：**

~~~python
"""按来源替换 Neo4j 中可检索切片。"""
from app.graph.neo4j_client import graph_driver
from app.rag.embedding import embed_many
from app.services.document_parser import split_text


async def replace_chunks(
    user_id: str, kind: str, source_id: str, title: str, content: str
) -> None:
    parts = split_text(content)[:50]
    vectors = await embed_many(parts)
    driver = graph_driver()
    async with driver.session() as session:
        async with await session.begin_transaction() as tx:
            await tx.run(
                "MATCH (c:Chunk {user_id:$uid,kind:$kind,source_id:$sid}) DETACH DELETE c",
                uid=user_id, kind=kind, sid=source_id,
            )
            for index, (part, vector) in enumerate(zip(parts, vectors)):
                await tx.run(
                    "CREATE (c:Chunk {id:$id,user_id:$uid,kind:$kind,"
                    "source_id:$sid,source_name:$title,chunk_index:$index,"
                    "text:$text,embedding:$vector})",
                    id=f"{kind}:{source_id}:{index}", uid=user_id, kind=kind,
                    sid=source_id, title=title[:255], index=index,
                    text=part, vector=vector,
                )
            await tx.commit()


async def delete_chunks(user_id: str, kind: str, source_id: str) -> None:
    await graph_driver().execute_query(
        "MATCH (c:Chunk {user_id:$uid,kind:$kind,source_id:$sid}) DETACH DELETE c",
        uid=user_id, kind=kind, sid=source_id,
    )
~~~

**整体解释：** 先批量编码，成功后才在一个图事务中替换这个来源的旧 Chunk；编码失败时旧向量还在，可由工单重试。远程模式把最多 10 片放在一次请求里，避免 50 个串行网络往返。MySQL 切片供详情页读取，Neo4j Chunk 是检索索引副本，两份数据在 Worker 完成前可能暂时不一致。

### 步骤 8：【修改】backend/app/graph/worker.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/worker.py
~~~

**修改定位与前后对照：** 实体与 Chunk 都完成才标任务完成。

~~~diff
+from app.rag.chunk_index import delete_chunks, replace_chunks
@@
         if source is None:
             await delete_source(user_id, kind, source_id)
+            await delete_chunks(user_id, kind, source_id)
@@
             await replace_source(user_id, kind, source_id, title, result)
+            await replace_chunks(user_id, kind, source_id, title, content)
~~~

**整体解释：** 同一来源有实体图和向量两份索引。实体抽取成功、向量失败时，任务仍应 pending/failed；重试会再次替换，两份索引最终追平。它们不是跨 Neo4j/MySQL 的单一事务，不能向页面承诺瞬时一致。

### 步骤 9：【运行验证】模型探针

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv run python -m compileall -q app main.py
uv run python - <<'PY'
import asyncio
from app.rag.embedding import embed
async def main():
    print(len(await embed("复刻项目测试笔记")))
asyncio.run(main())
PY
~~~

预期长度 512。当前项目实际使用 QwenCloud `text-embedding-v4`，两次真实输入都返回 512 维，L2 范数约等于 1；启动 FastAPI 时预热请求命中 `https://maas.qianwenaiapi.com/compatible-mode/v1/embeddings`。切换 provider 后，第 42 篇之前已有资料需按 `user_id/source_id` 重新入队，不能用零向量或不同模型的旧向量伪造索引。验证时现有 Neo4j Chunk 为 0，因此本次无需重建历史向量；以后已有数据时，应先记录旧模型、批量重算，再切换查询。
