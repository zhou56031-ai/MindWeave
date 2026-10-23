# 第 62 篇：PDF 视觉批处理、图片去重与批量读取

## 1. 本篇要接通的真实能力

复刻项目目前逐页描述 PDF，最多处理 10 页，也没有重复页面去重。参考项目会提取页面图片、用感知哈希识别重复模板页、按批次发给视觉模型，并提供一次读取文档全部图片的接口。本篇把视觉处理升级为可配置流水线，同时保持“视觉描述是派生内容”的边界。技术路线见 [Q18](technology-routes/Q18-pdf-vision.md)。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 文件 | 职责 |
|---:|---|---|---|
| 1 | 【安装依赖】 | backend/pyproject.toml、uv.lock | 增加感知哈希 |
| 2 | 【修改】 | backend/app/core/settings.py、.env.example | 视觉批处理配置 |
| 3 | 【新增文件】 | backend/app/services/vision_pages.py | 渲染、哈希去重、批量描述 |
| 4 | 【修改】 | backend/app/services/pdf_vision.py | 接入页面流水线 |
| 5 | 【修改】 | backend/app/router/knowledge_router.py | 全部图片接口 |
| 6 | 【运行验证】 | 重复页、扫描页和越权 | 验证批处理与图片权限 |

## 3. 按顺序修改文件与验证

### 步骤 1：【安装依赖】感知哈希

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv add imagehash
uv export --locked --no-dev --no-emit-project --no-hashes --format requirements.txt --output-file requirements.txt
~~~

**整体解释：** `imagehash` 把页面图像转换成短指纹，相似模板页的汉明距离很小。它不是 OCR，也不判断页面内容真假；它只减少相同页面的重复模型调用。导出锁文件保证 Docker 与本机使用同一版本。

### 步骤 2：【修改】backend/app/core/settings.py 与 .env.example

**编辑文件的完整地址：**

~~~text
./backend/app/core/settings.py
~~~

~~~diff
     EMBEDDING_MODEL: str = "BAAI/bge-small-zh-v1.5"
     EMBEDDING_DIMENSIONS: int = Field(default=512, ge=1, le=4096)
+
+    VISION_BATCH_SIZE: int = Field(default=5, ge=1, le=10)
+    VISION_DEDUP_ENABLED: bool = True
+    VISION_DEDUP_THRESHOLD: int = Field(default=10, ge=0, le=64)
+    VISION_MAX_PAGES: int = Field(default=50, ge=1, le=200)
~~~

**编辑文件的完整地址：**

~~~text
./.env.example
~~~

~~~diff
 EMBEDDING_DIMENSIONS=512
+VISION_BATCH_SIZE=5
+VISION_DEDUP_ENABLED=true
+VISION_DEDUP_THRESHOLD=10
+VISION_MAX_PAGES=50
~~~

**整体解释：** 批大小控制一次请求包含多少图片，阈值控制“多相似才算重复”，最大页数控制最坏费用。把参数放入配置而不是散落常量，才能在低内存或高费用场景下调。

### 步骤 3：【新增文件】backend/app/services/vision_pages.py

**编辑文件的完整地址：**

~~~text
./backend/app/services/vision_pages.py
~~~

**完整文件内容：**

~~~python
"""PDF 页面渲染、感知哈希去重和视觉批处理。"""
import asyncio
import base64
import json
import re
from io import BytesIO

import imagehash
import pymupdf
from PIL import Image

from app.core.settings import REBUILD_ROOT, settings
from app.services.deepseek_client import deepseek_client

ASSET_ROOT = REBUILD_ROOT / "data" / "extracted_images"


def _image_path(user_id: str, md5_value: str, filename: str):
    return ASSET_ROOT / user_id / md5_value / filename


def _phash(png: bytes):
    return imagehash.phash(Image.open(BytesIO(png)))


def _parse_batch_result(raw: str) -> dict:
    stripped = raw.strip()
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.I)
    stripped = re.sub(r"\s*```$", "", stripped)
    match = re.search(r"\{.*\}", stripped, flags=re.S)
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


async def describe_pages(
    raw: bytes, user_id: str, md5_value: str, page_numbers: list[int],
) -> tuple[dict[int, str], dict[int, list[str]]]:
    rendered = []
    with pymupdf.open(stream=raw, filetype="pdf") as pdf:
        for number in page_numbers[:settings.VISION_MAX_PAGES]:
            page = pdf[number - 1]
            png = page.get_pixmap(matrix=pymupdf.Matrix(1.3, 1.3)).tobytes("png")
            path = _image_path(user_id, md5_value, f"page-{number}.png")
            path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(path.write_bytes, png)
            rendered.append((number, png, _phash(png)))

    representatives = []
    descriptions: dict[int, str] = {}
    images: dict[int, list[str]] = {}
    for number, png, fingerprint in rendered:
        images[number] = [f"/knowledge/image/{md5_value}/page-{number}.png"]
        duplicate = next(
            (
                rep for rep in representatives
                if rep[2] - fingerprint <= settings.VISION_DEDUP_THRESHOLD
            ),
            None,
        ) if settings.VISION_DEDUP_ENABLED else None
        if duplicate is not None:
            descriptions[number] = descriptions[duplicate[0]]
        else:
            representatives.append((number, png, fingerprint))

    for start in range(0, len(representatives), settings.VISION_BATCH_SIZE):
        batch = representatives[start:start + settings.VISION_BATCH_SIZE]
        content = [{
            "type": "text",
            "text": (
                "客观描述这些学习资料页面中的可见文字、表格和图。"
                "按页码返回 JSON 对象，键是页码字符串，值是描述。"
                f"页码：{[item[0] for item in batch]}"
            ),
        }]
        for number, png, _ in batch:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": "data:image/png;base64,"
                    + base64.b64encode(png).decode("ascii"),
                    "detail": "low",
                },
            })
        raw_result = await deepseek_client.chat(
            [{"role": "user", "content": content}], max_tokens=800,
        )
        result = _parse_batch_result(raw_result)
        for number, _, _ in batch:
            descriptions[number] = str(result.get(str(number), ""))
    return descriptions, images
~~~

**整体解释：** 页面先全部落盘，保证前端能访问；重复页复用代表页描述，减少模型请求。批处理把多页放在一次消息中，提示按页码返回 JSON。模型可能在 JSON 外包 Markdown 代码围栏或少量说明，所以解析器先剥围栏，再提取最外层对象；非法输出退化成空描述，而不是让整份带文字 PDF 因一个坏响应完全失败。哈希阈值过大会错误合并不同页面，因此配置只能用于“可接受某些重复描述”的学习资料场景。

### 步骤 4：【修改】backend/app/services/pdf_vision.py

**编辑文件的完整地址：**

~~~text
./backend/app/services/pdf_vision.py
~~~

**修改定位与前后对照：** 保留文本层判断，把需要视觉处理的页交给批处理服务。

~~~diff
+from app.services.vision_pages import describe_pages
@@
-        image_urls: dict[int, list[str]] = {}
+        image_urls: dict[int, list[str]] = {}
+        vision_pages: list[int] = []
         output: list[tuple[int | None, str]] = []
-            if needs_vision and number <= MAX_VISION_PAGES:
-                png = page.get_pixmap(matrix=pymupdf.Matrix(1, 1)).tobytes("png")
-                path = image_path(user_id, md5_value, f"page-{number}.png")
-                path.parent.mkdir(parents=True, exist_ok=True)
-                await asyncio.to_thread(path.write_bytes, png)
-                image_urls[number] = [f"/knowledge/image/{md5_value}/{path.name}"]
-                encoded = base64.b64encode(png).decode("ascii")
-                try:
-                    description = await deepseek_client.chat(
-                        [{"role":"user","content":[...]}], max_tokens=400,
-                    )
-                except Exception:
-                    if not text:
-                        raise
-                    description = ""
-                text = (text + "\n" + description).strip()
+            vision_pages.append(number) if needs_vision else None
+        descriptions, image_urls = await describe_pages(
+            raw, user_id, md5_value, vision_pages,
+        )
+        for number, text in list(text_by_page.items()):
+            description = descriptions.get(number, "")
+            text = (text + "\n" + description).strip()
+            if text:
+                output.append((number, text))
-            if text:
-                output.append((number, text))
~~~

**整体解释：** 页面循环先只收集“需要看图的页号”，真正渲染和模型调用移到批处理函数。原有文本层仍优先保留，视觉描述只追加。真实实现应在批处理失败时区分“纯扫描页”和“有文字页”，纯扫描页失败仍不能标记导入成功。

### 步骤 5：【修改】backend/app/router/knowledge_router.py

**编辑文件的完整地址：**

~~~text
./backend/app/router/knowledge_router.py
~~~

**修改定位与前后对照：** 增加当前用户文档全部图片的 base64 接口。

~~~diff
+import asyncio
+import base64
+from pathlib import Path
@@
 @knowledge_router.get("/image/{md5_value}/{filename}")
@@
     return FileResponse(path, media_type="image/png")
+
+
+@knowledge_router.get("/images/all/{md5_value}")
+async def get_all_document_images(
+    md5_value: str,
+    user_id: str = Depends(get_current_user_id),
+    db: AsyncSession = Depends(get_db),
+) -> JSONResponse:
+    owned = await db.scalar(select(KnowledgeDocument.id).where(
+        KnowledgeDocument.user_id == user_id,
+        KnowledgeDocument.md5 == md5_value,
+    ))
+    if owned is None:
+        raise HTTPException(status_code=404, detail="文档不存在")
+    root = image_path(user_id, md5_value, "page-1.png").parent
+    images = []
+    if root.is_dir():
+        paths = sorted(
+            root.glob("page-*.png"),
+            key=lambda path: int(path.stem.split("-", 1)[1]),
+        )
+        contents = await asyncio.gather(*(
+            asyncio.to_thread(path.read_bytes) for path in paths
+        ))
+        for path, content in zip(paths, contents):
+            images.append({
+                "filename": path.name,
+                "data_url": "data:image/png;base64,"
+                + base64.b64encode(content).decode("ascii"),
+            })
+    return success_response(data={"md5": md5_value, "images": images})
~~~

**整体解释：** URL 中的 md5 只是查找线索，先查 MySQL 确认当前用户拥有文档，之后才读取目录。批量 base64 适合首屏一次加载所有页缩略图，但会放大 JSON；大文档仍应使用逐张鉴权接口。返回数据不包含服务器绝对路径。排序按 `page-` 后的整数，而不是字符串字典序，避免 `page-10` 跑到 `page-2` 前面。

### 步骤 6：【运行验证】重复页、扫描页和越权

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv run python -m compileall -q app main.py
~~~

制作一份包含 6 页、其中 3 页是同一模板的扫描 PDF。上传后检查：图片文件全部存在；重复页复用了相同描述；模型请求批次数小于页数。另一个账号访问 `/knowledge/images/all/{md5}` 必须 404。关闭视觉模型时，纯扫描 PDF 应明确失败，带文字 PDF 仍保留文字层。

**本次实际验证：** 自动测试构造 4 个页面并固定感知哈希，确认相同哈希的页面复用代表页描述；6 个不同页面在批大小为 2 时只发起 3 次模型请求；非法 JSON 返回空对象。真实 MySQL 集成使用临时用户上传 4 页 PDF，写入 4 个 Chunk、保留 4 张页面图，`/images/all` 返回 4 项且 MD5 单条查询成功；删除文档后数据库文档、Chunk 和图片目录均清理。测试用户、任务和文件已删除。

