# 第 37 篇：PDF、Word、PPT 的文字导入与页码

## 1. 本篇要接通的真实能力

当前 /knowledge/add/single 和多文件接口只解析 TXT、MD。本篇先接入 PDF、DOCX、PPTX 中**可提取的文字**，把 PDF 页码和 PPT 幻灯片序号保存到已有 KnowledgeChunk.page。扫描件、图片说明留给下一篇。这里写的是待操作教程；代码尚未因生成文档而自动完成。技术路线比较见 [Q17](technology-routes/Q17-document-parsing.md)。

## 2. 文件变化和操作顺序

| 顺序 | 标记 | 文件 | 职责 |
|---:|---|---|---|
| 1 | 【安装依赖】 | backend/pyproject.toml、uv.lock、requirements.txt | 增加解析库 |
| 2 | 【修改】 | backend/app/services/document_parser.py | 统一文件大小边界 |
| 3 | 【新增文件】 | backend/app/services/document_extract.py | 提取文字和页号 |
| 4 | 【修改】 | backend/app/services/knowledge_service.py | 逐页切片并保存 |

固定复刻根目录：.。继续使用当前虚拟环境和 MySQL，不重新初始化。

## 3. 按顺序修改文件与验证

### 步骤 1：【安装依赖】三种格式解析器

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv add pymupdf python-docx python-pptx
uv export --locked --no-dev --no-emit-project --no-hashes --format requirements.txt --output-file requirements.txt
~~~

pyproject 声明直接依赖，uv.lock 固定本机解析结果，requirements.txt 从锁文件生成。PyMuPDF 提取 PDF 页文字；另两库解析 Office Open XML。此步骤不需要手工改锁文件。

### 步骤 2：【修改】backend/app/services/document_parser.py

**编辑文件的完整地址：**

~~~text
./backend/app/services/document_parser.py
~~~

**修改定位与前后对照：** 找 MAX_FILE_BYTES 与 parse_text_document 中的大小错误。

~~~diff
-MAX_FILE_BYTES = 2 * 1024 * 1024
+# 【修改】所有上传路由与解析服务共用这一字节上限。
+MAX_FILE_BYTES = 10 * 1024 * 1024
@@
-        raise BusinessException(code=4001, message="文件必须非空且不超过 2 MB")
+        raise BusinessException(code=4001, message="文件必须非空且不超过 10 MB")
~~~

**整体解释：** 这像上传窗口共用的一把尺：路由按 MAX_FILE_BYTES + 1 读取，解析器按同一个值拒绝超限。只改解析库而不改这把尺，较大的 PDF 会在进入解析器之前就被截断。10 MB 是原始文件字节上限，不等于模型上下文长度；切片仍限制送往后续检索的文字。

### 步骤 3：【新增文件】backend/app/services/document_extract.py

**编辑文件的完整地址：**

~~~text
./backend/app/services/document_extract.py
~~~

**完整文件内容：**

~~~python
"""从支持的文件中取得安全文件名和 (页号, 正文)。"""
from io import BytesIO
from pathlib import Path

import fitz
from docx import Document
from docx.table import Table
from pptx import Presentation

from app.core.failed_response import BusinessException
from app.services.document_parser import MAX_FILE_BYTES, parse_text_document


def extract_pages(filename: str, raw: bytes) -> tuple[str, list[tuple[int | None, str]]]:
    safe_name = filename.replace("\\", "/").split("/")[-1].strip()
    suffix = Path(safe_name).suffix.lower()
    if not safe_name or len(safe_name) > 255 or suffix not in {".txt", ".md", ".pdf", ".docx", ".pptx"}:
        raise BusinessException(code=4001, message="文件类型不支持")
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise BusinessException(code=4001, message="文件必须非空且不超过 10 MB")
    if suffix in {".txt", ".md"}:
        _, text = parse_text_document(safe_name, raw)
        return safe_name, [(None, text)]
    try:
        if suffix == ".pdf":
            with fitz.open(stream=raw, filetype="pdf") as pdf:
                pages = [(number + 1, page.get_text("text")) for number, page in enumerate(pdf)]
        elif suffix == ".docx":
            doc = Document(BytesIO(raw))
            parts = []
            for block in doc.iter_inner_content():
                if isinstance(block, Table):
                    parts.extend(" | ".join(cell.text for cell in row.cells)
                                 for row in block.rows)
                else:
                    parts.append(block.text)
            pages = [(None, "\n".join(parts))]
        else:
            slides = Presentation(BytesIO(raw))
            pages = []
            for number, slide in enumerate(slides.slides, start=1):
                parts = []
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        parts.append(shape.text)
                    if shape.has_table:
                        parts.extend(" | ".join(cell.text for cell in row.cells)
                                     for row in shape.table.rows)
                pages.append((number, "\n".join(parts)))
    except Exception as exc:
        raise BusinessException(code=4001, message="文件损坏或无法解析") from exc
    pages = [(number, text.strip()) for number, text in pages if text.strip()]
    if not pages:
        raise BusinessException(code=4001, message="文件没有可提取文字")
    return safe_name, pages
~~~

**整体解释：** 不同格式像不同装订方式的书，服务只接受统一的“第几页写了什么”。本文件不连接数据库；它把恶意客户端路径缩成文件名，再让解析库拿到内存字节。Word 按文档顺序遍历段落和表格，PPT 按幻灯片顺序遍历文字形状与表格；表格用竖线保留大致列界，但合并单元格、嵌套表格和复杂视觉顺序不能保证原样还原。DOCX 没有可靠的实际打印页码，因此用 None，不编造数字。扫描 PDF 若整份没有可提取文字会明确失败，不会留下空文档。

### 步骤 4：【修改】backend/app/services/knowledge_service.py

**编辑文件的完整地址：**

~~~text
./backend/app/services/knowledge_service.py
~~~

**修改定位与前后对照：** 只改 add_document 的解析、切片与 KnowledgeChunk 构造；原来的 MD5 去重和单事务提交继续保留。

~~~diff
-from app.services.document_parser import parse_text_document, split_text
+from app.services.document_parser import split_text
+from app.services.document_extract import extract_pages
@@ async def add_document(
-        safe_name, content = parse_text_document(filename, raw)
+        safe_name, pages = extract_pages(filename, raw)
+        content = "\n\n".join(text for _, text in pages)
@@
-        pieces = split_text(content)
+        pieces = [(page, part) for page, text in pages for part in split_text(text)]
@@
-                    content=piece, images=[],
+                    content=piece, page=page, images=[],
@@
-                for index, piece in enumerate(pieces)
+                for index, (page, piece) in enumerate(pieces)
~~~

**整体解释：** 原服务把整份纯文本直接切成索引卡；现在先分清页面，再在每页内部切卡，并把页码盖到每张卡上。父文档与切片仍一次 commit，某张卡失败不会留下半本书。详情的 content 继续是全文，前端的 chunks 响应因此能显示页号。上传同名或同内容文件依旧由原有用户范围唯一约束处理。

### 步骤 5：【运行验证】解析与事务

**执行目录的完整地址：**

~~~text
./backend
~~~

~~~bash
uv run python -m compileall -q app main.py
uv sync --locked --check
~~~

准备小型 PDF、DOCX、PPTX，经已登录的 /knowledge/add/single 上传，再用 /knowledge/chunks?filename=文件名读取：PDF/PPT 切片应有页号，DOCX 为 null。用无文字扫描件验证失败后 /knowledge/list 不新增行；用重复文件验证仍会拒绝。以上是执行步骤与预期，不能把本篇文档生成当作已实测。
