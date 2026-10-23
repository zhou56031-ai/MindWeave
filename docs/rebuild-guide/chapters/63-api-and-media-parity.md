# 第 63 篇：补齐头像、MD5、非流式上传和导出接口

## 1. 本篇要接通的真实能力

参考项目中还有几个前端 endpoint 尚未在复刻后端实现，包括 `/file/upload/`、`/knowledge/add/multiple`、MD5 单条查询与 clear、笔记 export。本篇补齐这些缺口。头像文件写入受控 media 目录，知识库 MD5 仍是 MySQL 业务数据，任何接口都不能接受客户端自称的 user_id。接口总览参考[差异审计](../concepts/02-reference-vs-rebuild-gap-audit.md)。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 文件 | 职责 |
|---:|---|---|---|
| 1 | 【新增文件】 | backend/app/router/file_router.py | 头像上传 |
| 2 | 【修改】 | backend/main.py、docker-compose.yml | 注册文件路由并持久化 media |
| 3 | 【修改】 | backend/app/services/knowledge_service.py | MD5 详情与保留文档清理 |
| 4 | 【修改】 | backend/app/router/knowledge_router.py | 新知识库端点 |
| 5 | 【修改】 | backend/app/router/note_router.py | export 别名 |
| 6 | 【运行验证】 | 头像、MD5 和上传 | 响应与用户隔离 |

## 3. 按顺序修改文件与验证

### 步骤 1：【新增文件】backend/app/router/file_router.py

**编辑文件的完整地址：**

~~~text
./backend/app/router/file_router.py
~~~

**完整文件内容：**

~~~python
"""用户头像上传。"""
import asyncio
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import REBUILD_ROOT
from app.db.db_config import get_db
from app.models.user_model import User
from app.utils.auth_utils import get_current_user_id

file_router = APIRouter(prefix="/file", tags=["file"])
MEDIA_ROOT = REBUILD_ROOT / "media"
ALLOWED = {".png", ".jpg", ".jpeg", ".webp"}


@file_router.post("/upload/")
async def upload_avatar(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(status_code=422, detail="头像只支持 PNG/JPG/WebP")
    raw = await file.read()
    if not raw or len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="头像需非空且不超过 5 MB")
    filename = uuid4().hex + suffix
    target = MEDIA_ROOT / "img" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(target.write_bytes, raw)
    try:
        user = await db.scalar(select(User).where(User.uuid == user_id))
        if user is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        user.avatar = f"/media/img/{filename}"
        await db.commit()
    except Exception:
        await db.rollback()
        target.unlink(missing_ok=True)
        raise
    return {
        "success": True,
        "data": {"url": user.avatar, "alt": "用户头像", "href": user.avatar},
    }
~~~

**整体解释：** 文件名由服务端 UUID 生成，客户端原名只用于取后缀，不能借此写到任意路径。文件先落盘、用户归属通过 JWT 查出，再更新 avatar；文件系统写入放到线程中，避免大文件阻塞事件循环。任何数据库查询或提交失败都会回滚事务并删除刚写文件，缩小“数据库无记录但磁盘有孤儿文件”的窗口。

### 步骤 2：【修改】backend/main.py

**编辑文件的完整地址：**

~~~text
./backend/main.py
~~~

~~~diff
+from fastapi.staticfiles import StaticFiles
+from app.core.settings import REBUILD_ROOT
+from app.router.file_router import file_router
@@
 app.include_router(graph_router)
+app.include_router(file_router)
+media_root = REBUILD_ROOT / "media"
+media_root.mkdir(parents=True, exist_ok=True)
+app.mount("/media", StaticFiles(directory=media_root), name="media")
 register_exception_handlers(app)
~~~

**整体解释：** `include_router` 只注册上传动作，`StaticFiles` 让浏览器读取保存后的头像 URL。media 是公开静态文件，不能把私人 PDF 图片放在里面；知识文档图片仍走 JWT 鉴权路由。

容器部署还要给 backend 与 worker 挂同一 media 卷，否则重建容器后头像 URL 会指向不存在的文件：

~~~diff
     volumes:
       - extracted_data:/srv/data
+      - media_data:/srv/media
       - model_cache:/model-cache
@@
 volumes:
   mysql_data:
   redis_data:
   neo4j_data:
   extracted_data:
+  media_data:
   model_cache:
~~~

### 步骤 3：【修改】backend/app/services/knowledge_service.py

**编辑文件的完整地址：**

~~~text
./backend/app/services/knowledge_service.py
~~~

**修改定位与前后对照：** 增加单条 MD5 记录与“只清记录/保留文档”的方法。

~~~diff
+    async def get_md5(self, db: AsyncSession, user_id: str, md5_value: str):
+        row = await db.scalar(select(KnowledgeDocument).where(
+            KnowledgeDocument.user_id == user_id,
+            KnowledgeDocument.md5 == md5_value,
+        ))
+        if row is None:
+            return None
+        return MD5Record(
+            md5=row.md5, filename=row.filename, original_filename=row.filename,
+            upload_time=row.created_at.isoformat(),
+        )
+
+    async def clear_md5(
+        self, db: AsyncSession, user_id: str, delete_documents: bool,
+    ) -> int:
+        if not delete_documents:
+            raise BusinessException(
+                code=4002,
+                message="当前 MySQL 权威文档模型不支持保留正文单独清空 MD5",
+            )
+        return await self.clean_all(db, user_id)
~~~

**整体解释：** 参考项目可以把“去重记录”和正文分开处理，但本复刻的 MySQL 文档行同时保存正文、Chunk 外键和 MD5 唯一键。如果 `delete_documents=False` 时静默删掉文档行，接口名字会承诺“保留文档”却实际丢正文；因此当前实现明确返回业务错误 `4002`。只有 `delete_documents=true` 才调用完整清理。未来若拆出去重表，才应在这里实现“保留正文、清 MD5”。这种显式能力边界比伪造兼容更安全。

### 步骤 4：【修改】backend/app/router/knowledge_router.py

**编辑文件的完整地址：**

~~~text
./backend/app/router/knowledge_router.py
~~~

**修改定位与前后对照：** 增加非流式多文件、单条 MD5 和 clear。

~~~diff
 @knowledge_router.post("/add/multiple/stream")
@@
     return StreamingResponse(
@@
     )
+
+
+@knowledge_router.post("/add/multiple")
+async def add_multiple_documents(
+    files: list[UploadFile] = File(...),
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> JSONResponse:
+    if len(files) > 5:
+        raise HTTPException(status_code=422, detail="一次最多上传 5 个文件")
+    names = []
+    try:
+        for file in files:
+            raw = await file.read(MAX_FILE_BYTES + 1)
+            document = await knowledge_service.add_document(
+                db, user_id, file.filename or "", raw,
+            )
+            names.append(document.filename)
+    finally:
+        for file in files:
+            await file.close()
+    return success_response(message="多文件导入成功", data={"filenames": names})
@@
 @knowledge_router.get("/md5/list")
@@
     return success_response(data=await knowledge_service.list_md5(db, user_id))
+
+
+@knowledge_router.get("/md5/{md5_value}")
+async def get_md5_record(
+    md5_value: str,
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> JSONResponse:
+    row = await knowledge_service.get_md5(db, user_id, md5_value)
+    if row is None:
+        raise HTTPException(status_code=404, detail="MD5 记录不存在")
+    return success_response(data=row)
+
+
+@knowledge_router.delete("/md5/clear")
+async def clear_md5_records(
+    delete_documents: bool = True,
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> JSONResponse:
+    count = await knowledge_service.clear_md5(db, user_id, delete_documents)
+    return success_response(message=f"已清理 {count} 条记录")
~~~

**整体解释：** 非流式接口在请求结束前完成全部文件，前端能一次拿到文件名列表；某一份失败会抛错，已提交的前几份不会自动回滚，这是与参考项目“逐文件独立”必须写清的边界。MD5 查询和 clear 都先按 JWT 用户筛选，不信任 URL 中的 md5。

### 步骤 5：【修改】backend/app/router/note_router.py

**编辑文件的完整地址：**

~~~text
./backend/app/router/note_router.py
~~~

~~~diff
 @note_router.get("/{note_id}/download")
@@
     return Response(
         content=markdown.encode("utf-8"), media_type="text/markdown; charset=utf-8",
         headers={"Content-Disposition": f'attachment; filename="{note_id}.md"'},
     )
+
+
+@note_router.get("/{note_id}/export")
+async def export_note(
+    note_id: str,
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> Response:
+    markdown = await note_service.export_note_markdown(db, user_id, note_id)
+    if markdown is None:
+        raise HTTPException(status_code=404, detail="笔记不存在")
+    return Response(
+        content=markdown.encode("utf-8"),
+        media_type="text/markdown; charset=utf-8",
+    )
~~~

**整体解释：** `export` 与 `download` 共享同一 Markdown 生成器，区别只在响应头。两个入口都能返回当前用户笔记，另一个用户 UUID 统一 404。前端未来可以按接口偏好切换。

### 步骤 6：【运行验证】头像、MD5 和上传

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv run python -m compileall -q app main.py
~~~

上传 PNG 头像，确认 `/media/img/...` 可访问且用户详情 avatar 已更新。用错误后缀上传应 422。上传两份 txt 到 `/knowledge/add/multiple`，列表应新增两行；查询其中一份 MD5 成功，另一账号查询 404。调用 `/knowledge/md5/clear?delete_documents=true` 后列表为空，PDF 图片目录也应清理。调用 `/note/{id}/export`，响应正文应包含 frontmatter 和 Markdown。

**本次实际验证：** 最终 82 个自动测试中，头像成功落盘和数据库提交失败后的文件补偿均有覆盖；前端契约测试确认 `/file/upload/`、非流式多上传、MD5 单条/clear、`/note/{id}/export` 全部注册。真实 MySQL 的 4 页 PDF 验证同时调用了 MD5 单条查询和文档删除清理路径。`delete_documents=false` 保持明确 4002，不标记为与参考项目完全一致。

