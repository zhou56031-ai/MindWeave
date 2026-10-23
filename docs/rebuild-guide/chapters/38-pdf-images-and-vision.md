# 第 38 篇：PDF 页面图片、视觉描述与安全读取

## 1. 本篇要接通的真实能力

第 37 篇只能读 PDF 中已有的文字；扫描页往往是图片。本篇把最多十页需要视觉理解的 PDF 页面渲染成图片，保存到复刻项目独立数据目录，让 DeepSeek 描述图片中的可见文字和图表，再把描述并入切片。前端使用的 /knowledge/image/{md5}/{filename} 只能读取**当前登录用户**文档的图片。模型描述是辅助材料，不能冒充原始 PDF 文字。DeepSeek 图像输入格式以[官方 Vision 文档](https://api-docs.deepseek.com/guides/vision/)为准；技术比较见 [Q18](technology-routes/Q18-pdf-vision.md)。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 文件 | 职责 |
|---:|---|---|---|
| 1 | 【修改】 | backend/app/services/deepseek_client.py | 接受多模态消息内容 |
| 2 | 【修改】 | backend/app/services/document_extract.py | 保留 PDF 空文字页交给视觉处理 |
| 3 | 【新增文件】 | backend/app/services/pdf_vision.py | 渲染、描述并保存页面图片 |
| 4 | 【修改】 | backend/app/services/knowledge_service.py | 视觉描述进入全文和切片 |
| 5 | 【修改】 | backend/app/router/knowledge_router.py | 授权后读取图片 |

图片目录在复刻根目录 data/extracted_images 下；第 52 篇部署时会挂持久卷。不要把图片写到前端 public 目录，否则绕过后端鉴权。

## 3. 按顺序修改文件与验证

### 步骤 1：【修改】backend/app/services/deepseek_client.py

**编辑文件的完整地址：**

~~~text
./backend/app/services/deepseek_client.py
~~~

**修改定位与前后对照：** 两个方法都接受同一种 messages 结构；本篇只调用非流式 chat。

~~~diff
-        self, messages: Sequence[dict[str, str]], *, max_tokens: int = 700
+        self, messages: Sequence[dict[str, Any]], *, max_tokens: int = 700
@@
-        messages: Sequence[dict[str, str]],
+        messages: Sequence[dict[str, Any]],
~~~

**整体解释：** 原客户端假定每条消息的 content 都是字符串；图片消息的 content 实际是文字块与 image_url 块组成的列表。只放宽类型声明，原来的 key、超时、状态码检查仍是统一门卫；视觉业务不重新拼一套鉴权 HTTP 客户端。

### 步骤 2：【修改】backend/app/services/document_extract.py

**编辑文件的完整地址：**

~~~text
./backend/app/services/document_extract.py
~~~

**修改定位与前后对照：** 在 extract_pages 返回前保留 PDF 空页。

~~~diff
-    pages = [(number, text.strip()) for number, text in pages if text.strip()]
+    # 【修改】扫描 PDF 的空文字页可能有图，留给视觉服务处理。
+    pages = [(number, text.strip()) for number, text in pages
+             if suffix == ".pdf" or text.strip()]
~~~

**整体解释：** 前一篇把“没有抽出字的页”直接扔掉，等于视觉服务还没上场，扫描页就不见了。现在 PDF 保留空页号；其它格式仍过滤空页。文件确实零页时继续报错，视觉调用失败且整份无文字时由下一步明确拒绝。

### 步骤 3：【新增文件】backend/app/services/pdf_vision.py

**编辑文件的完整地址：**

~~~text
./backend/app/services/pdf_vision.py
~~~

**完整文件内容：**

~~~python
"""PDF 页面渲染、视觉描述与用户范围内图片路径。"""
import asyncio
import base64
import re
import shutil
from pathlib import Path

import fitz
from fastapi import HTTPException

from app.core.settings import REBUILD_ROOT
from app.services.deepseek_client import deepseek_client

ASSET_ROOT = REBUILD_ROOT / "data" / "extracted_images"
PAGE_NAME = re.compile(r"page-[1-9][0-9]*\.png")
MAX_VISION_PAGES = 10


def image_path(user_id: str, md5_value: str, filename: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", md5_value) or not PAGE_NAME.fullmatch(filename):
        raise HTTPException(status_code=404, detail="图片不存在")
    return ASSET_ROOT / user_id / md5_value / filename


def remove_images(user_id: str, md5_value: str) -> None:
    shutil.rmtree(ASSET_ROOT / user_id / md5_value, ignore_errors=True)


async def enrich_pdf(
    raw: bytes, user_id: str, md5_value: str,
    pages: list[tuple[int | None, str]],
) -> tuple[list[tuple[int | None, str]], dict[int, list[str]]]:
    text_by_page = {number: text for number, text in pages}
    image_urls: dict[int, list[str]] = {}
    output: list[tuple[int | None, str]] = []
    with fitz.open(stream=raw, filetype="pdf") as pdf:
        for index, page in enumerate(pdf):
            number = index + 1
            text = text_by_page.get(number, "")
            needs_vision = len(text) < 100 or bool(page.get_images())
            if needs_vision and number <= MAX_VISION_PAGES:
                # PyMuPDF 页面在当前线程渲染；磁盘写入再交给线程池。
                png = page.get_pixmap(matrix=fitz.Matrix(1, 1)).tobytes("png")
                path = image_path(user_id, md5_value, f"page-{number}.png")
                path.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(path.write_bytes, png)
                image_urls[number] = [f"/knowledge/image/{md5_value}/{path.name}"]
                encoded = base64.b64encode(png).decode("ascii")
                try:
                    description = await deepseek_client.chat([{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "请客观描述此学习资料页面可见文字、表格和图；不要补造看不见的内容。"},
                            {"type": "image_url", "image_url": {
                                "url": "data:image/png;base64," + encoded, "detail": "low",
                            }},
                        ],
                    }], max_tokens=400)
                except Exception:
                    if not text:
                        raise
                    description = ""
                text = (text + "\n" + description).strip()
            if text:
                output.append((number, text))
    if not output:
        raise HTTPException(status_code=422, detail="PDF 没有可读取内容")
    return output, image_urls
~~~

**整体解释：** 每页先找原文；若字少或含图片，就渲染缩略图并请模型描述。存图路径只由服务端用户 ID、已算出的 MD5 和固定页号构成，浏览器提交的文件名不能变成任意磁盘路径。已有文字的页在模型暂时失败时仍保留原文；纯扫描页没有描述则失败，不伪造“导入成功”。十页上限是费用与等待时间边界，超过部分仍可导入已有文字，正式扩容应移到后台任务。

### 步骤 4：【修改】backend/app/services/knowledge_service.py

**编辑文件的完整地址：**

~~~text
./backend/app/services/knowledge_service.py
~~~

**修改定位与前后对照：** add_document 中先完成现有去重查询，再调用视觉服务；同时修改切片 images 字段。

~~~diff
+from app.services.pdf_vision import enrich_pdf, remove_images
@@ async def add_document(
-        content = "\n\n".join(text for _, text in pages)
         digest = md5(raw).hexdigest()
@@
         if existing is not None:
             raise BusinessException(code=4002, message="文件名或文件内容已导入")
+        page_images = {}
+        if safe_name.lower().endswith(".pdf"):
+            try:
+                pages, page_images = await enrich_pdf(raw, user_id, digest, pages)
+            except Exception:
+                remove_images(user_id, digest)
+                raise
+        content = "\n\n".join(text for _, text in pages)
@@
-                    content=piece, page=page, images=[],
+                    content=piece, page=page,
+                    images=page_images.get(page, []),
@@
         except IntegrityError as exc:
             await db.rollback()
+            remove_images(user_id, digest)
@@ async def delete_document(
         await db.commit()
+        remove_images(user_id, document.md5)
         return True
~~~

**整体解释：** 服务先查重，避免重复文件也付视觉调用费；视觉描述得到后才构造全文和切片，图片 URL 与该页切片绑在一起。数据库提交和文件系统写入不是一个事务：这里对已知的解析和唯一键失败做清理，但进程在两者中间突然崩溃仍可能留下孤儿文件，后台清扫属于后续可靠性工作。删除文档先提交数据库删除，再移除本用户这份 MD5 的图片，不能让其他用户同 MD5 的图片受影响。

### 步骤 5：【修改】backend/app/router/knowledge_router.py

**编辑文件的完整地址：**

~~~text
./backend/app/router/knowledge_router.py
~~~

**修改定位与前后对照：** 导入 FileResponse、select、KnowledgeDocument 和 image_path；把固定路由放在本路由组末尾也不会与 /detail 冲突。

~~~diff
-from fastapi.responses import JSONResponse, StreamingResponse
+from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
+from sqlalchemy import select
+from app.models.knowledge_document import KnowledgeDocument
+from app.services.pdf_vision import image_path
+
+@knowledge_router.get("/image/{md5_value}/{filename}")
+async def get_pdf_image(
+    md5_value: str,
+    filename: str,
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> FileResponse:
+    owned = await db.scalar(select(KnowledgeDocument.id).where(
+        KnowledgeDocument.user_id == user_id,
+        KnowledgeDocument.md5 == md5_value,
+    ))
+    path = image_path(user_id, md5_value, filename)
+    if owned is None or not path.is_file():
+        raise HTTPException(status_code=404, detail="图片不存在")
+    return FileResponse(path, media_type="image/png")
~~~

**整体解释：** URL 中的 MD5 只是查找线索，不是通行证。路由先用 JWT 用户 ID 验证这份文档归属，再让严格页文件名规则生成路径；只有两项都通过才交给 FileResponse。别人的 MD5、伪造目录穿越和缺失文件统一 404，避免图片从静态目录直接泄漏。

### 步骤 6：【运行验证】扫描页和越权图片

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv run python -m compileall -q app main.py
~~~

使用自己制作的小型扫描 PDF 上传后，/knowledge/chunks 应含视觉描述和 images URL；本账号访问图片 HTTP 200，第二账号访问相同 URL 为 404。重复上传不应再次创建文档。测试用 PDF 页面数控制在十页以内，避免把未实现的后台任务能力当成已完成。
