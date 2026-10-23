"""Neo4j 异步驱动与最小图约束。"""

from fastapi import HTTPException
from neo4j import AsyncDriver, AsyncGraphDatabase

from app.core.settings import settings

_driver: AsyncDriver | None = None


def graph_driver() -> AsyncDriver:
    global _driver
    if not settings.NEO4J_URI or not settings.NEO4J_PASSWORD.get_secret_value():
        raise HTTPException(status_code=503, detail="图服务未配置")
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD.get_secret_value()),
        )
    return _driver


async def ensure_graph_schema() -> None:
    driver = graph_driver()
    await driver.verify_connectivity()
    statements = [
        "CREATE CONSTRAINT entity_type_user_name IF NOT EXISTS "
        "FOR (t:EntityType) REQUIRE (t.user_id, t.name) IS UNIQUE",
        "CREATE CONSTRAINT manual_relation_id IF NOT EXISTS "
        "FOR ()-[r:MANUAL_RELATION]-() REQUIRE r.id IS UNIQUE",
        "CREATE CONSTRAINT source_user_kind_id IF NOT EXISTS "
        "FOR (s:Source) REQUIRE (s.user_id, s.kind, s.id) IS UNIQUE",
        "CREATE CONSTRAINT entity_id IF NOT EXISTS "
        "FOR (e:Entity) REQUIRE e.id IS UNIQUE",
        "CREATE CONSTRAINT note_id IF NOT EXISTS "
        "FOR (n:Note) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT doc_user_id IF NOT EXISTS "
        "FOR (d:Doc) REQUIRE (d.id, d.user_id) IS UNIQUE",
        "CREATE CONSTRAINT chunk_user_id IF NOT EXISTS "
        "FOR (c:Chunk) REQUIRE (c.id, c.user_id) IS UNIQUE",
        "CREATE INDEX entity_user IF NOT EXISTS FOR (e:Entity) ON (e.user_id)",
        "CREATE INDEX source_user IF NOT EXISTS FOR (s:Source) ON (s.user_id)",
        "CREATE INDEX chunk_user IF NOT EXISTS FOR (c:Chunk) ON (c.user_id)",
    ]
    for statement in statements:
        await driver.execute_query(statement)
    index_name = "chunk_embedding_index"
    existing = (await driver.execute_query(
        "SHOW VECTOR INDEXES YIELD name, options "
        "WHERE name = $name RETURN options",
        name=index_name,
    )).records
    if existing:
        options = existing[0]["options"] or {}
        old_dimensions = (options.get("indexConfig") or {}).get("vector.dimensions")
        if old_dimensions is not None and int(old_dimensions) != settings.EMBEDDING_DIMENSIONS:
            raise RuntimeError("已有向量索引维度不同，必须规划重建")
    await driver.execute_query(
        "CREATE VECTOR INDEX chunk_embedding_index IF NOT EXISTS "
        "FOR (c:Chunk) ON c.embedding "
        "OPTIONS {indexConfig: {"
        f"`vector.dimensions`: {settings.EMBEDDING_DIMENSIONS}, "
        "`vector.similarity_function`: 'cosine'}}"
    )
    analyzer = settings.RAG_FULLTEXT_ANALYZER
    if analyzer not in {"standard", "simple", "whitespace", "stop", "cjk"}:
        analyzer = "standard"
    await driver.execute_query(
        "CREATE FULLTEXT INDEX chunk_text_index IF NOT EXISTS "
        "FOR (c:Chunk) ON EACH [c.text] "
        f"OPTIONS {{indexConfig: {{`fulltext.analyzer`: '{analyzer}'}}}}"
    )


async def close_graph_driver() -> None:
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None
