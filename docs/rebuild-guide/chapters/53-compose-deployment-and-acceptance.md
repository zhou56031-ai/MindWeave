# 第 53 篇：容器启动、重启持久化与整体验收

## 1. 本篇要接通的真实能力

到这里，笔记、知识文档、图谱、检索、聊天、审批和回顾都有对应后端教程。本篇把后端 API、图 Worker 和已经复制好的前端放进同一套 Compose，检验关机再启动后 MySQL、Redis、Neo4j 与 PDF 图片仍在。部署取舍见 [Q28](technology-routes/Q28-compose-deployment-and-data.md)。

本篇只教后端镜像、Compose 与验收；前端已有 Dockerfile 和 nginx.conf，直接使用，不再逐文件讲前端。浏览器仍访问 127.0.0.1:3100，后端直连端口 8100。Compose 内的服务名 mysql/redis/neo4j 代替宿主机 127.0.0.1；若把宿主机地址照搬进容器，连接会指向容器自己。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 文件 | 职责 |
|---:|---|---|---|
| 1 | 【新增文件】 | backend/Dockerfile | 构建 FastAPI 与 Worker 共用镜像 |
| 2 | 【新增文件】 | backend/.dockerignore | 不把虚拟环境与本地秘密打包 |
| 3 | 【修改】 | docker-compose.yml | 加 backend、worker、front 与持久卷 |
| 4 | 【修改】 | .env.example | 说明容器所需变量 |
| 5 | 【运行验证】 | Compose 与浏览器 | 首次启动、重启、断线和用户隔离 |

Docker Compose 适合单机学习与本机复刻；多机发布需要另行处理镜像仓库、数据库备份、迁移、TLS、日志和可用性。本篇不执行删除卷命令。现有 .env 中的真实 DeepSeek 密钥不写入文档，也不放进镜像构建参数。

## 3. 按顺序修改文件与验证

### 步骤 1：【新增文件】backend/Dockerfile

**编辑文件的完整地址：**

~~~text
./backend/Dockerfile
~~~

**完整文件内容：**

~~~dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/model-cache

WORKDIR /srv/backend

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY main.py ./main.py

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
~~~

**整体解释：** requirements.txt 来自前面 uv 的锁定导出；镜像构建只复制依赖清单、应用代码和入口。运行时配置由 Compose 环境传入，不把 .env 复制进镜像。HF_HOME 指向单独卷，Worker 重启时不用每次重新下载本地嵌入模型。API 和 Worker 共用同一镜像，但启动命令不同；这样两者用同一份应用版本。

### 步骤 2：【新增文件】backend/.dockerignore

**编辑文件的完整地址：**

~~~text
./backend/.dockerignore
~~~

**完整文件内容：**

~~~text
.venv
__pycache__
*.pyc
.env
.env.*
data
logs
.pytest_cache
~~~

**整体解释：** 这是“交给 Docker 构建器的行李清单”。本机虚拟环境、缓存、秘密和用户资料都不该进入构建上下文；真正需要的数据在运行时通过持久卷挂载。此文件不改变本机 .gitignore 的作用。

### 步骤 3：【修改】docker-compose.yml

**编辑文件的完整地址：**

~~~text
./docker-compose.yml
~~~

**修改定位与前后对照：** 保留现有 mysql、redis、neo4j 服务，在 neo4j 后、services 末尾增加三个服务；在 volumes 末尾登记两个新卷。以下 YAML 缩进与现有服务同级。

~~~diff
 services:
@@
   neo4j:
@@
     volumes:
       - neo4j_data:/data
+
+  backend:
+    build: ./backend
+    restart: unless-stopped
+    environment: &backend_env
+      APP_NAME: RAGNotebook Rebuild
+      ENV: prod
+      MYSQL_HOST: mysql
+      MYSQL_PORT: 3306
+      MYSQL_USER: $MYSQL_USER
+      MYSQL_PASSWORD: $MYSQL_PASSWORD
+      MYSQL_DATABASE: $MYSQL_DATABASE
+      REDIS_HOST: redis
+      REDIS_PORT: 6379
+      REDIS_DB: 3
+      SECRET_KEY: $SECRET_KEY
+      DEEPSEEK_API_KEY: $DEEPSEEK_API_KEY
+      DEEPSEEK_API_KEY_BACKUP: $DEEPSEEK_API_KEY_BACKUP
+      DEEPSEEK_BASE_URL: $DEEPSEEK_BASE_URL
+      DEEPSEEK_MODEL: $DEEPSEEK_MODEL
+      NEO4J_URI: bolt://neo4j:7687
+      NEO4J_USER: neo4j
+      NEO4J_PASSWORD: $NEO4J_PASSWORD
+      EMBEDDING_MODEL: BAAI/bge-small-zh-v1.5
+      EMBEDDING_DIMENSIONS: 512
+    ports:
+      - "127.0.0.1:8100:8000"
+    volumes:
+      - extracted_data:/srv/data
+      - model_cache:/model-cache
+    depends_on:
+      mysql:
+        condition: service_healthy
+      redis:
+        condition: service_healthy
+      neo4j:
+        condition: service_started
+    healthcheck:
+      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=5)"]
+      interval: 10s
+      timeout: 6s
+      retries: 10
+      start_period: 30s
+
+  worker:
+    build: ./backend
+    restart: unless-stopped
+    command: ["python", "-m", "app.graph.worker"]
+    environment: *backend_env
+    volumes:
+      - extracted_data:/srv/data
+      - model_cache:/model-cache
+    depends_on:
+      mysql:
+        condition: service_healthy
+      neo4j:
+        condition: service_started
+
+  front:
+    build: ./front
+    restart: unless-stopped
+    ports:
+      - "127.0.0.1:3100:80"
+    depends_on:
+      backend:
+        condition: service_healthy
@@
 volumes:
   mysql_data:
   redis_data:
   neo4j_data:
+  extracted_data:
+  model_cache:
~~~

**整体解释：** 同一镜像启动两个进程：backend 处理请求，worker 消费图工单。MySQL、Redis、Neo4j 原来的卷继续保存业务状态；extracted_data 保存 PDF 图片；model_cache 保存本地模型文件。前端 nginx 已把同源 /note、/chat、/knowledge、/api/graph 等请求代理给名为 backend 的容器，所以浏览器不需要知道容器内端口。depends_on 只约束启动顺序；Neo4j 还可能尚未完成 Bolt 初始化，Worker 的 restart 策略会在启动失败后重试。若生产使用多台主机，镜像、卷与数据库不能照搬这个单机假设。

### 步骤 4：【修改】.env.example

**编辑文件的完整地址：**

~~~text
./.env.example
~~~

**修改定位与前后对照：** 在 Neo4j 示例键后加入说明，真实值继续只填在 Git 忽略的 .env。

~~~diff
 NEO4J_PASSWORD=
+# 容器部署时 Compose 用服务名覆盖 MYSQL_HOST、REDIS_HOST、NEO4J_URI；
+# 本文件中的 127.0.0.1 地址仍供宿主机直跑后端使用。
+# SECRET_KEY、MYSQL_PASSWORD、MYSQL_ROOT_PASSWORD、NEO4J_PASSWORD 请在 .env 设置独立随机值。
+# DEEPSEEK_API_KEY 留空时非 AI 接口可工作，AI 接口会明确失败。
~~~

**整体解释：** .env.example 是变量清单，不是可直接发布的密码文件。Compose 解析根目录 .env 后，把不同连接地址注入容器；宿主机运行 uvicorn 仍读 .env 里的 127.0.0.1 端口。两种运行方式不能同时占用 8100/3100，否则端口冲突；需要切换时先停止另一种进程。

### 步骤 5：【运行验证】先核配置，再构建启动

**执行目录的完整地址：**

~~~text
.
~~~

~~~bash
docker compose config --quiet
docker compose build backend worker front
docker compose up -d
docker compose ps
curl -i http://127.0.0.1:8100/health/live
curl -i http://127.0.0.1:8100/health/ready
curl -I http://127.0.0.1:3100/
~~~

**整体解释：** config 先检查变量和 YAML；build 证明前后端都可从源码重建；up 启动全部服务。/live 只证明进程能回应，/ready 检查 MySQL 与 Redis。图谱健康要额外用图页面或 Worker 日志验证，不把 ready=200 误解为 Neo4j 和模型也正常。若 neo4j 因密码未配置未启动，先补 .env 再重启对应服务。

### 步骤 6：【运行验证】按真实用户路径验收

**执行目录的完整地址：**

~~~text
.
~~~

用两个本机测试账号逐项走页面：登录后分别建同名笔记；编辑标题、正文、标签、分类与置顶；筛选、搜索、导出、删除；上传 TXT/MD/PDF/DOCX/PPTX，核对文档详情、切片和 PDF 图片；等图任务从 pending 到 completed，在图谱里搜索、打开来源、手工建实体关系、合并与重抽；在 AIChat 提问并检查 thinking 来源 ID、流式结束与会话刷新；要求创建笔记，拒绝一次、同意一次，核对写入只发生一次；完成今日回顾并生成选择题。对另一账号的每个笔记、文档、图节点、会话 ID 尝试访问，应拒绝或返回空，不能显示其正文。没有 DeepSeek 凭据或图服务不可用时，对应 AI/图步骤记录实际失败，不能将其记成“通过”。

### 步骤 7：【运行验证】持久化与恢复

**执行目录的完整地址：**

~~~text
.
~~~

~~~bash
docker compose restart backend worker front
docker compose ps
curl -i http://127.0.0.1:8100/health/ready
~~~

重启后打开同一账号，笔记、知识文档、PDF 图片、图谱与会话历史应仍在；未决审批应仍可从 GET pending 恢复，已完成审批不能再次执行。再暂停 Worker，编辑一篇测试笔记，确认任务保持 pending；恢复 Worker 后观察它完成。最后只使用 docker compose stop 停服务，不能用 down -v 清除卷。验收记录应写真实结果、失败原因和复现步骤；文档本身只是操作说明，不代表这些步骤已由助手或读者实际执行。
