# 第 65 篇：前端契约、完整回归与最终验收

## 1. 本篇要接通的真实能力

前 54–64 篇补齐了参考项目的主要行为，但“代码存在”不等于“页面可用”。本篇建立一套最终契约：前端 endpoint 都有后端路由，双账号隔离由自动化覆盖，后端测试、前端构建和 Compose 配置都能重复执行。完成后，才算把 RAGNotebook 从章节教程收束为可交付复刻项目。技术路线见 [Q28](technology-routes/Q28-compose-deployment-and-data.md)。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 文件 | 职责 |
|---:|---|---|---|
| 1 | 【新增文件】 | backend/tests/test_endpoint_parity.py | 前端 endpoint 与后端路由对照 |
| 2 | 【新增文件】 | backend/tests/test_acceptance_contracts.py | 最终 API 和健康契约 |
| 3 | 【新增文件】 | backend/tests/test_ops_governance.py、test_vision_pages.py | 限流、预热、头像、图和视觉回归 |
| 4 | 【修改】 | README.md、roadmap.md、教程目录 | 更新实际完成与未验证状态 |
| 5 | 【运行验证】 | 后端、前端和 Compose | 全量回归 |
| 6 | 【运行验证】 | 双账号浏览器路径 | 最终人工验收 |

## 3. 按顺序修改文件与验证

### 步骤 1：【新增文件】backend/tests/test_endpoint_parity.py

**编辑文件的完整地址：**

~~~text
./backend/tests/test_endpoint_parity.py
~~~

**完整文件内容：**

~~~python
"""Frontend endpoints must map to real FastAPI routes."""
import unittest

from main import app


EXPECTED_ROUTES = {
    # Auth, profile, and avatar
    ("/user/login/", "POST"),
    ("/user/logout/", "POST"),
    ("/user/register/", "POST"),
    ("/user/refresh-token/", "POST"),
    ("/user/detail/", "GET"),
    ("/user/update/", "PUT"),
    ("/user/reset-password/", "POST"),
    ("/file/upload/", "POST"),
    # Notes
    ("/note/create", "POST"),
    ("/note/list", "GET"),
    ("/note/search", "GET"),
    ("/note/stats", "GET"),
    ("/note/{note_id}", "GET"),
    ("/note/{note_id}", "PUT"),
    ("/note/{note_id}", "DELETE"),
    ("/note/{note_id}/pin", "PUT"),
    ("/note/{note_id}/related", "GET"),
    ("/note/{note_id}/download", "GET"),
    ("/note/{note_id}/export", "GET"),
    ("/note/{note_id}/auto-tag", "POST"),
    ("/note/autocomplete", "POST"),
    ("/note/assist/stream", "POST"),
    ("/note/batch/delete", "POST"),
    ("/note/batch/download", "POST"),
    ("/note/batch/category", "PUT"),
    ("/note/batch/pin", "PUT"),
    ("/note/category/{category}", "DELETE"),
    # Chat, knowledge, and graph
    ("/chat/agent/query/stream", "POST"),
    ("/chat/agent/resume", "POST"),
    ("/chat/reorder", "POST"),
    ("/chat/sessions", "GET"),
    ("/chat/sessions/{path_user_id}", "GET"),
    ("/chat/session/{session_id}", "GET"),
    ("/chat/session/{session_id}", "DELETE"),
    ("/chat/session/{session_id}/pending", "GET"),
    ("/chat/session/{session_id}/approval", "GET"),
    ("/knowledge/add/single", "POST"),
    ("/knowledge/add/multiple", "POST"),
    ("/knowledge/add/multiple/stream", "POST"),
    ("/knowledge/list", "GET"),
    ("/knowledge/detail", "GET"),
    ("/knowledge/chunks", "GET"),
    ("/knowledge/clean", "DELETE"),
    ("/knowledge/delete/filename", "DELETE"),
    ("/knowledge/image/{md5_value}/{filename}", "GET"),
    ("/knowledge/images/all/{md5_value}", "GET"),
    ("/knowledge/md5/list", "GET"),
    ("/knowledge/md5/{md5_value}", "GET"),
    ("/knowledge/md5/delete/{md5_value}", "DELETE"),
    ("/knowledge/md5/clear", "DELETE"),
    ("/api/graph/overview", "GET"),
    ("/api/graph/events", "GET"),
    ("/api/graph/extract-logs", "GET"),
    ("/api/graph/entity/{entity_id}", "GET"),
    ("/api/graph/entity/{entity_id}/neighbors", "GET"),
    ("/api/graph/entity/{entity_id}/notes", "GET"),
    ("/api/graph/notes/{note_id}/related", "GET"),
    ("/api/graph/notes/{note_id}/re-extract", "POST"),
    ("/api/graph/docs/{doc_id}/related", "GET"),
    ("/api/graph/search", "GET"),
    ("/api/graph/entities", "POST"),
    ("/api/graph/entities/{entity_id}", "PUT"),
    ("/api/graph/entities/{entity_id}", "DELETE"),
    ("/api/graph/entities/merge", "POST"),
    ("/api/graph/types", "GET"),
    ("/api/graph/types", "POST"),
    ("/api/graph/types/{type_id}", "PUT"),
    ("/api/graph/types/{type_id}", "DELETE"),
    ("/api/graph/relations", "POST"),
    ("/api/graph/relations/{relation_id}", "DELETE"),
    # Review and templates
    ("/review/today", "GET"),
    ("/review/done/{note_id}", "POST"),
    ("/review/question/{note_id}", "GET"),
    ("/note-template/list", "GET"),
    ("/note-template/create", "POST"),
    ("/note-template/reorder", "PUT"),
    ("/note-template/{template_id}", "PUT"),
    ("/note-template/{template_id}", "DELETE"),
}


class EndpointParityTests(unittest.TestCase):
    def test_every_frontend_endpoint_has_matching_method(self):
        routes = {
            (route.path, method)
            for route in app.routes
            for method in (getattr(route, "methods", None) or [])
        }
        self.assertLessEqual(EXPECTED_ROUTES, routes)


if __name__ == "__main__":
    unittest.main()
~~~

**整体解释：** 这个测试不验证业务正确性，只防止“页面调用了一个后端根本不存在的路径或方法”。路径参数名必须和真实注册一致；`{md5}` 与 `{md5_value}` 的差异应以 FastAPI 实际 path 为准，否则静态对照会产生假失败。`Mount` 没有 `methods` 属性，所以所有遍历都使用 `getattr(route, "methods", None)`，新增 `/media` 静态挂载后旧测试也因此兼容。

### 步骤 2：【新增文件】backend/tests/test_acceptance_contracts.py

**编辑文件的完整地址：**

~~~text
./backend/tests/test_acceptance_contracts.py
~~~

**完整文件内容：**

~~~python
"""Final acceptance checks that do not require external services."""
import unittest

from fastapi.testclient import TestClient

from main import app


class AcceptanceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.routes = {
            (route.path, method)
            for route in app.routes
            for method in (getattr(route, "methods", None) or [])
        }

    def test_health_security_and_docs_routes(self):
        expected = {
            ("/health/live", "GET"),
            ("/health/ready", "GET"),
            ("/openapi.json", "GET"),
            ("/user/login/", "POST"),
            ("/user/refresh-token/", "POST"),
        }
        self.assertLessEqual(expected, self.routes)

    def test_agent_approval_and_graph_rebuild_routes(self):
        expected = {
            ("/chat/agent/resume", "POST"),
            ("/chat/session/{session_id}/approval", "GET"),
            ("/api/graph/notes/{note_id}/re-extract", "POST"),
        }
        self.assertLessEqual(expected, self.routes)

    def test_media_mount_and_process_time_header(self):
        names = {getattr(route, "name", "") for route in app.routes}
        self.assertIn("media", names)
        client = TestClient(app)
        try:
            response = client.get("/health/live")
        finally:
            client.close()
        self.assertEqual(response.status_code, 200)
        self.assertIn("X-Process-Time", response.headers)
        self.assertGreaterEqual(float(response.headers["X-Process-Time"]), 0)


if __name__ == "__main__":
    unittest.main()
~~~

**整体解释：** 最终测试分成“无外部依赖契约”和“需要真实 MySQL/Neo4j 的集成测试”两层。上面的 `TestClient` 不进入 lifespan 上下文，因此只执行 HTTP 中间件和健康路由，不启动数据库、模型预热或 Worker。真实导入、审批、限流和图谱仍按前面章节的集成脚本验证。

### 步骤 3：【新增文件】治理与视觉回归

**编辑文件的完整地址：**

~~~text
./backend/tests/test_ops_governance.py
~~~

**完整文件内容：**

~~~python
"""Rate limiting, warmup, avatar, and graph maintenance contracts."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException

from app.core.rate_limit import rate_limit
from app.core.warmup import warm_embedding
from app.graph.maintenance import ensure_system_types
from app.graph.task_queue import enqueue_graph
from app.router.file_router import upload_avatar


class RateLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_over_limit_returns_429(self):
        request = SimpleNamespace(
            client=SimpleNamespace(host="127.0.0.1"),
            headers={},
        )
        redis = SimpleNamespace(
            incr=AsyncMock(return_value=3),
            expire=AsyncMock(),
        )
        with (
            patch("app.core.rate_limit.settings.RATE_LIMIT_ENABLED", True),
            patch("app.core.rate_limit.get_redis", return_value=redis),
        ):
            dependency = rate_limit("chat", 2)
            with self.assertRaises(HTTPException) as raised:
                await dependency(request)

        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(raised.exception.headers["Retry-After"], "60")

    async def test_disabled_limit_does_not_touch_redis(self):
        redis_factory = Mock()
        with (
            patch("app.core.rate_limit.settings.RATE_LIMIT_ENABLED", False),
            patch("app.core.rate_limit.get_redis", redis_factory),
        ):
            await rate_limit("chat", 1)(SimpleNamespace(client=None))
        redis_factory.assert_not_called()

    async def test_redis_failure_returns_503(self):
        request = SimpleNamespace(
            client=SimpleNamespace(host="127.0.0.1"),
            headers={},
        )
        redis = SimpleNamespace(incr=AsyncMock(side_effect=ConnectionError("down")))
        with (
            patch("app.core.rate_limit.settings.RATE_LIMIT_ENABLED", True),
            patch("app.core.rate_limit.get_redis", return_value=redis),
        ):
            with self.assertRaises(HTTPException) as raised:
                await rate_limit("chat", 2)(request)
        self.assertEqual(raised.exception.status_code, 503)

    async def test_valid_proxy_client_ip_is_used_in_key(self):
        request = SimpleNamespace(
            client=SimpleNamespace(host="172.18.0.5"),
            headers={"x-real-ip": "203.0.113.9"},
        )
        redis = SimpleNamespace(incr=AsyncMock(return_value=1), expire=AsyncMock())
        with (
            patch("app.core.rate_limit.settings.RATE_LIMIT_ENABLED", True),
            patch("app.core.rate_limit.get_redis", return_value=redis),
        ):
            await rate_limit("chat", 2)(request)
        key = redis.incr.await_args.args[0]
        self.assertIn(":203.0.113.9:", key)


class WarmupTests(unittest.IsolatedAsyncioTestCase):
    async def test_warmup_failure_is_isolated(self):
        with patch(
            "app.core.warmup.embed",
            AsyncMock(side_effect=RuntimeError("model unavailable")),
        ):
            await warm_embedding()


class AvatarTests(unittest.IsolatedAsyncioTestCase):
    async def test_avatar_is_saved_and_owned_by_token_user(self):
        class Upload:
            filename = "avatar.png"

            async def read(self):
                return b"image-data"

        user = SimpleNamespace(avatar=None)
        db = SimpleNamespace(
            scalar=AsyncMock(return_value=user),
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        with tempfile.TemporaryDirectory() as temp:
            with patch("app.router.file_router.MEDIA_ROOT", Path(temp)):
                result = await upload_avatar(Upload(), "user-1", db)
                target = Path(temp) / result["data"]["url"].removeprefix("/media/")
                self.assertTrue(target.is_file())
                self.assertEqual(target.read_bytes(), b"image-data")

        self.assertEqual(user.avatar, result["data"]["url"])

    async def test_failed_database_commit_removes_uploaded_file(self):
        class Upload:
            filename = "avatar.jpg"

            async def read(self):
                return b"image-data"

        user = SimpleNamespace(avatar=None)
        db = SimpleNamespace(
            scalar=AsyncMock(return_value=user),
            commit=AsyncMock(side_effect=RuntimeError("db down")),
            rollback=AsyncMock(),
        )
        with tempfile.TemporaryDirectory() as temp:
            with patch("app.router.file_router.MEDIA_ROOT", Path(temp)):
                with self.assertRaises(RuntimeError):
                    await upload_avatar(Upload(), "user-1", db)
                files = list(Path(temp).rglob("*"))
                self.assertEqual([path for path in files if path.is_file()], [])


class GraphMaintenanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_system_types_are_seeded_per_user(self):
        driver = SimpleNamespace(execute_query=AsyncMock(return_value=SimpleNamespace()))
        with patch("app.graph.maintenance.graph_driver", return_value=driver):
            await ensure_system_types("user-1")
        self.assertEqual(driver.execute_query.await_count, 4)
        self.assertTrue(all(
            call.kwargs["uid"] == "user-1"
            for call in driver.execute_query.await_args_list
        ))
        query = driver.execute_query.await_args_list[0].args[0]
        self.assertLess(query.index("ON CREATE SET"), query.index("SET t.display_name"))

    async def test_enqueue_persists_snapshot_and_force(self):
        db = SimpleNamespace(scalar=AsyncMock(return_value=None), add=Mock())
        await enqueue_graph(
            db, "user-1", "doc", "doc-1",
            title="guide.pdf", content_hash="abc",
            payload={"chunks": [1, 2]}, force=True,
        )
        task = db.add.call_args.args[0]
        self.assertEqual(task.title, "guide.pdf")
        self.assertEqual(task.content_hash, "abc")
        self.assertEqual(task.payload, '{"chunks": [1, 2]}')
        self.assertEqual(task.force, 1)


if __name__ == "__main__":
    unittest.main()
~~~

**编辑文件的完整地址：**

~~~text
./backend/tests/test_vision_pages.py
~~~

**完整文件内容：**

~~~python
"""PDF visual batching, duplicate reuse, and image lifecycle."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import imagehash
import pymupdf

from app.router.knowledge_router import get_all_document_images
from app.services import vision_pages
from app.services.pdf_vision import remove_images


def make_pdf(page_count: int) -> bytes:
    document = pymupdf.open()
    try:
        for index in range(page_count):
            page = document.new_page()
            page.insert_text((72, 72), f"page {index + 1}")
        return document.tobytes()
    finally:
        document.close()


class VisionPageTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_pages_reuse_representative_description(self):
        first = imagehash.hex_to_hash("0000000000000000")
        second = imagehash.hex_to_hash("ffffffffffffffff")
        chat = AsyncMock(return_value='{"1":"same","3":"other"}')
        with tempfile.TemporaryDirectory() as temp:
            with (
                patch.object(vision_pages, "ASSET_ROOT", Path(temp)),
                patch.object(vision_pages, "_phash", side_effect=[
                    first, first, second, second,
                ]),
                patch.object(vision_pages.settings, "VISION_DEDUP_ENABLED", True),
                patch.object(vision_pages.settings, "VISION_DEDUP_THRESHOLD", 0),
                patch.object(vision_pages.settings, "VISION_BATCH_SIZE", 5),
                patch.object(vision_pages.deepseek_client, "chat", chat),
            ):
                descriptions, images = await vision_pages.describe_pages(
                    make_pdf(4), "user-1", "a" * 32, [1, 2, 3, 4],
                )

        self.assertEqual(chat.await_count, 1)
        self.assertEqual(descriptions[1], "same")
        self.assertEqual(descriptions[2], "same")
        self.assertEqual(descriptions[3], "other")
        self.assertEqual(descriptions[4], "other")
        self.assertEqual(len(images), 4)

    async def test_representatives_are_sent_in_configured_batches(self):
        fingerprints = [
            imagehash.hex_to_hash(f"{index:016x}")
            for index in range(1, 7)
        ]
        chat = AsyncMock(return_value="{}")
        with tempfile.TemporaryDirectory() as temp:
            with (
                patch.object(vision_pages, "ASSET_ROOT", Path(temp)),
                patch.object(vision_pages, "_phash", side_effect=fingerprints),
                patch.object(vision_pages.settings, "VISION_DEDUP_ENABLED", True),
                patch.object(vision_pages.settings, "VISION_DEDUP_THRESHOLD", 0),
                patch.object(vision_pages.settings, "VISION_BATCH_SIZE", 2),
                patch.object(vision_pages.deepseek_client, "chat", chat),
            ):
                await vision_pages.describe_pages(
                    make_pdf(6), "user-1", "b" * 32, [1, 2, 3, 4, 5, 6],
                )
        self.assertEqual(chat.await_count, 3)

    def test_invalid_batch_json_becomes_empty_description(self):
        self.assertEqual(vision_pages._parse_batch_result("not json"), {})
        self.assertEqual(
            vision_pages._parse_batch_result('```json\n{"1":"ok"}\n```'),
            {"1": "ok"},
        )


class ImageLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_images_are_owned_and_naturally_ordered(self):
        class DB:
            async def scalar(self, _statement):
                return "document-id"

        md5_value = "c" * 32
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "user-1" / md5_value
            root.mkdir(parents=True)
            for number in (10, 2, 1):
                (root / f"page-{number}.png").write_bytes(b"png")
            with patch("app.services.pdf_vision.ASSET_ROOT", Path(temp)):
                response = await get_all_document_images(
                    md5_value, "user-1", DB(),
                )

        payload = json.loads(response.body)
        filenames = [
            item["filename"] for item in payload["data"]["images"]
        ]
        self.assertEqual(filenames, ["page-1.png", "page-2.png", "page-10.png"])

    def test_remove_images_deletes_only_requested_document(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "user-1" / ("d" * 32)
            other = Path(temp) / "user-1" / ("e" * 32)
            target.mkdir(parents=True)
            other.mkdir(parents=True)
            (target / "page-1.png").write_bytes(b"png")
            (other / "page-1.png").write_bytes(b"png")
            with patch("app.services.pdf_vision.ASSET_ROOT", Path(temp)):
                remove_images("user-1", "d" * 32)
            self.assertFalse(target.exists())
            self.assertTrue(other.exists())


if __name__ == "__main__":
    unittest.main()
~~~

**整体解释：** 最终回归不只看路由是否存在，还要覆盖治理与多模态最容易退化的边界：限流超限、Redis 故障、头像提交失败、系统类型 Cypher、重复页复用、坏模型 JSON 和页序。测试通过临时目录和 mock 隔离外部资源，能在 CI 快速执行；数据库与图库的真实集成另按第 61、62 篇验证。

### 步骤 4：【修改】README.md 与 roadmap.md

**编辑文件的完整地址：**

~~~text
./README.md
~~~

**修改定位与前后对照：** 把“PDF/Office、聊天和图谱仍待实现”的旧状态改为当前真实进度。

~~~diff
-`backend/`：已代执行后端教程第 01–26 篇；第 23 篇文本解析器原已存在。包含 FastAPI、MySQL 笔记与知识文档、用户、JWT、Redis、模板、Markdown/ZIP 导出及 TXT/MD 单/多文件导入、详情与删除。PDF/Office、聊天和图谱仍待实现。
+`backend/`：已接入教程第 01–65 篇的主线能力，包括多格式文档、PDF 视觉批处理、Neo4j 图谱、Embedding、混合检索、Agentic RAG、工具审批、抽取审计、限流与后台预热。
+`front/`：TypeScript 与 Vite 生产构建通过。
+截至 2026-10-21，后端 82 个无外部依赖测试通过；QwenCloud Embedding、旧表迁移、真实 Redis 限流、Neo4j 维护和 MySQL PDF 导入已单独验证。完整镜像构建与双账号浏览器人工验收仍待记录。
~~~

**编辑文件的完整地址：**

~~~text
./docs/rebuild-guide/roadmap.md
~~~

~~~diff
-> 更新：2026-10-21。后端第 01–60 篇对应主线能力已接入；第 61–65 篇继续对齐参考项目的抽取审计、多模态、剩余 API 与运维。
+> 更新：2026-10-21。后端第 01–65 篇对应能力已接入；抽取审计、多模态 PDF、剩余 API、限流/日志/预热和最终契约测试已完成。
~~~

**整体解释：** 文档状态必须和代码、测试结果同步。README 不能继续声称“PDF/聊天/图谱待实现”，也不能把“配置校验通过”写成“完整镜像部署通过”。因此状态分成代码接入、自动测试、真实服务集成和人工浏览器四层；没有执行的最后一层继续明确保留。

### 步骤 5：【运行验证】后端、前端和 Compose 全量回归

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv sync --locked --check
uv run python -m compileall -q app main.py
uv run python -m unittest discover -s tests -v
~~~

**执行目录的完整地址：**

~~~text
./front
~~~

~~~bash
npm run build
~~~

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

预期结果：

- 后端编译通过，全部测试通过。
- 前端 TypeScript 与 Vite 构建通过。
- Compose 配置通过，backend/worker/front 建成并启动。
- 8100 live/ready 为 200，3100 首页为 200。
- Worker 日志没有未捕获异常。

如果 Docker Hub 无法访问，可以先把可信的基础镜像重新打回 Dockerfile 使用的 tag；不要为了绕过网络修改应用协议。PyTorch 使用 CPU 版，若磁盘不足应先清理未使用构建缓存。

**本次实际执行结果：** `uv sync --locked --check` 确认锁文件无需变更；`compileall` 通过；`unittest discover` 共 82 个测试全部通过；`npm run build` 完成 TypeScript 与 Vite 生产构建，只提示 Graph 页面 chunk 超过 500 kB，不影响产物；`docker compose config --quiet` 通过。另外实际启动本地 FastAPI 与 Vite：lifespan、QwenCloud Embedding 预热和关闭清理正常，8100 live/ready、3100 首页以及 3100 代理的 ready 均为 200，响应包含 `X-Process-Time`。按用户此前要求不再重新下载数 GB 的 PyTorch 依赖，因此本轮没有执行 `docker compose build backend worker front` 和完整 `up`。教程保留构建命令供磁盘与网络允许时验收，不把配置校验替代构建结果。

### 步骤 6：【运行验证】双账号浏览器最终路径

**执行目录的完整地址：**

~~~text
.
~~~

用账号 A、B 各走一遍：

1. 登录、刷新令牌、注销后旧 token 失效。
2. 新建笔记，等待自动标签和分类。
3. 置顶、搜索同义短语、批量分类、导出和删除。
4. 上传 TXT、PDF、DOCX、PPTX，检查切片、页码、图片和删除。
5. 等图任务 completed，查看实体、关系、来源、双链和手工编辑。
6. 问一个图谱关系问题，确认 evidence 同时含 graph/note。
7. 问一个本地没有的“最新”问题，确认 Web 开关和来源边界。
8. 要求创建笔记，刷新恢复审批，拒绝一次、同意一次，确认只写一次。
9. 打开另一账号的 note/doc/session/entity ID，全部应 404 或空结果。

验收记录要写日期、容器状态、测试命令、失败原因和复现步骤。只有真实通过的项目才标记完成；没有外部 Key 时，AI 与 Web 步骤记录为“未验证”，不能写成“通过”。

**本次人工验收状态：** 当前执行环境没有浏览器自动化依赖，且没有按上述双账号路径逐页操作，因此第 1–9 项不标记通过。已经单独通过的是自动路由契约、真实 Redis 限流、真实 Neo4j 系统类型/孤儿清理、真实 MySQL 多页 PDF 和图片生命周期；这些结果不能替代对页面交互、审批刷新恢复和双账号可见性的最终人工检查。

