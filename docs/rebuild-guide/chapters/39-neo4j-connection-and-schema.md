# 第 39 篇：独立 Neo4j、连接生命周期与图约束

## 1. 本篇要接通的真实能力

第 35 篇的 MySQL 字面检索没有实体关系。本篇先给复刻项目建立独立 Neo4j 容器、配置和异步驱动，尚不写实体。参考项目把图节点、来源和后续向量切片放进 Neo4j；复刻时每条业务查询仍要携带 user_id。图服务不可用时，笔记 CRUD 继续运行，图接口在后续篇章返回 503。原理和同类存储比较见 [Q19](technology-routes/Q19-neo4j-graph-store.md)；容器设置依据 [Neo4j Docker 文档](https://neo4j.com/docs/operations-manual/current/docker/introduction/)。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 文件 | 职责 |
|---:|---|---|---|
| 1 | 【修改】 | docker-compose.yml、.env.example | 独立图服务 |
| 2 | 【安装依赖】 | backend/pyproject.toml、uv.lock、requirements.txt | Neo4j 驱动 |
| 3 | 【修改】 | backend/app/core/settings.py | 读取图配置 |
| 4 | 【新增文件】 | backend/app/graph/__init__.py、neo4j_client.py | 驱动与约束 |
| 5 | 【修改】 | backend/app/core/lifespan.py | 关闭连接池 |

Neo4j 使用复刻端口 17687/17474 和独立卷。已有 MySQL/Redis 数据不迁移、不删除。

## 3. 按顺序修改文件与验证

### 步骤 1：【修改】docker-compose.yml

**编辑文件的完整地址：**

~~~text
./docker-compose.yml
~~~

**修改定位与前后对照：** 在 services 的 redis 后新增服务，在 volumes 末尾登记新卷。

~~~diff
 services:
@@
   redis:
@@
       retries: 20
+
+  neo4j:
+    image: neo4j:5.26-community
+    restart: unless-stopped
+    environment:
+      NEO4J_AUTH: neo4j/${NEO4J_PASSWORD:?请在根目录.env中填写NEO4J_PASSWORD}
+    ports:
+      - "127.0.0.1:17474:7474"
+      - "127.0.0.1:17687:7687"
+    volumes:
+      - neo4j_data:/data
@@
 volumes:
   mysql_data:
   redis_data:
+  neo4j_data:
~~~

**整体解释：** 新容器像给项目增设图书馆，仍用自己的门牌和储藏室。宿主机端口绑定 127.0.0.1，避免和参考项目的 7474/7687 冲突；Neo4j 密码来自本机 .env。容器启动不等于 Bolt 认证成功，稍后会用驱动核验。不要复制参考项目的数据卷。

### 步骤 2：【修改】.env.example

**编辑文件的完整地址：**

~~~text
./.env.example
~~~

**修改定位与前后对照：** 追加示例键，真实密码只在被 Git 忽略的 .env 中填写。

~~~diff
 DEEPSEEK_MODEL=deepseek-flash
+NEO4J_URI=bolt://127.0.0.1:17687
+NEO4J_USER=neo4j
+NEO4J_PASSWORD=
~~~

**整体解释：** 示例文件说明位置，不是凭据库。URI 指向宿主机端口；若后端后来进入 Compose 网络，应改为 neo4j:7687，不能继续用容器内的 127.0.0.1。

### 步骤 3：【安装依赖】Neo4j 官方驱动

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv add neo4j
uv export --locked --no-dev --no-emit-project --no-hashes --format requirements.txt --output-file requirements.txt
~~~

### 步骤 4：【修改】backend/app/core/settings.py

**编辑文件的完整地址：**

~~~text
./backend/app/core/settings.py
~~~

**修改定位与前后对照：** 在 DeepSeek 配置后加入图配置。

~~~diff
     DEEPSEEK_MODEL: str = "deepseek-flash"
+    # 【新增】空 URI 允许非图功能独立启动。
+    NEO4J_URI: str = ""
+    NEO4J_USER: str = "neo4j"
+    NEO4J_PASSWORD: SecretStr = SecretStr("")
~~~

**整体解释：** Settings 是环境到 Python 的总闸。图驱动只从这里拿连接信息；留空 URI 时非图业务仍可启动。SecretStr 避免普通对象打印泄露密码，但日志也不要记录完整认证参数。

### 步骤 5：【新增文件】backend/app/graph/__init__.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/__init__.py
~~~

**完整文件内容：**

~~~python
"""用户范围内的知识图谱基础设施。"""
~~~

### 步骤 6：【新增文件】backend/app/graph/neo4j_client.py

**编辑文件的完整地址：**

~~~text
./backend/app/graph/neo4j_client.py
~~~

**完整文件内容：**

~~~python
"""Neo4j 异步驱动与最小图约束。"""
from fastapi import HTTPException
from neo4j import AsyncGraphDatabase

from app.core.settings import settings

_driver = None


def graph_driver():
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
        "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
        "CREATE CONSTRAINT note_id IF NOT EXISTS FOR (n:Note) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT doc_user_id IF NOT EXISTS FOR (d:Doc) REQUIRE (d.id, d.user_id) IS UNIQUE",
        "CREATE CONSTRAINT chunk_user_id IF NOT EXISTS FOR (c:Chunk) REQUIRE (c.id, c.user_id) IS UNIQUE",
        "CREATE INDEX entity_user IF NOT EXISTS FOR (e:Entity) ON (e.user_id)",
        "CREATE INDEX chunk_user IF NOT EXISTS FOR (c:Chunk) ON (c.user_id)",
    ]
    for statement in statements:
        await driver.execute_query(statement)


async def close_graph_driver() -> None:
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None
~~~

**整体解释：** 驱动是共享连接池，不是每次查询新建 TCP。约束登记图节点的业务键，后续 MERGE 与 MATCH 才有稳定落点；它不能替服务自动加 user_id 过滤。图 Schema 由图 worker 初始化，避免图故障拖垮笔记主流程；应用退出时关闭已经使用过的池。

### 步骤 7：【修改】backend/app/core/lifespan.py

**编辑文件的完整地址：**

~~~text
./backend/app/core/lifespan.py
~~~

**修改定位与前后对照：** 只在 finally 中补图驱动关闭。

~~~diff
+from app.graph.neo4j_client import close_graph_driver
@@
     finally:
+        await close_graph_driver()
         await close_redis()
~~~

**整体解释：** MySQL/Redis 仍决定主应用就绪；Neo4j 先独立失败。关闭时释放连接池，热重载不会一直留下旧连接。图密码错时应由图接口返回 503，不能连普通笔记也无法打开。

### 步骤 8：【运行验证】容器与认证

**执行目录的完整地址：**

~~~text
.
~~~

先在本机 .env 填 NEO4J_PASSWORD：

~~~bash
docker compose config --quiet
docker compose up -d neo4j
docker compose ps neo4j
~~~

再到复刻 backend 目录运行：

~~~bash
uv run python - <<'PY'
import asyncio
from app.graph.neo4j_client import ensure_graph_schema, close_graph_driver
async def main():
    try:
        await ensure_graph_schema()
        print("graph schema ready")
    finally:
        await close_graph_driver()
asyncio.run(main())
PY
~~~

看到 graph schema ready 才说明 Bolt 认证与建约束成功；本篇不执行清图或删除卷。
