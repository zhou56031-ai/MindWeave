# 第 23 篇：解析 TXT/Markdown 并切成可检索片段

> 前置：第 22 篇完成后的后端状态。解析文件已预先存在于正式复刻目录，并被第 24 篇真实上传流程使用。
> 成果：新增独立解析模块，识别 UTF-8 的 `.txt`、`.md`，统一换行，再把正文切成带重叠的文本片段。
> 验证标记：解析器经正式后端的 Markdown 上传、切片持久化和不支持类型校验间接验证；本篇未单独新增文件。

**技术路线原理与同类比较：** [Q11：固定字符、递归结构与 token 切片](technology-routes/Q11-text-chunking.md)。

## 1. 本篇目标与对齐边界

新增独立解析模块，识别 UTF-8 的 `.txt`、`.md`，统一换行，再把正文切成带重叠的文本片段。

参考项目的 `AsyncTextSplitter` 会结合配置、分隔符甚至嵌入模型。本篇先做确定性的字符切片，方便验证存储链路；语义切分留到后续检索阶段。

本篇只动后端。原项目的前端已经直接复制到复刻目录；你无需新建或修改前端文件。后端讲解沿真实的 `router → schema → service → model/数据库` 关系进行，不重复已掌握的 Python 基础语法。

## 2. 目录与文件变化

本篇沿用现有 `backend/app` 目录；只有下表标为【新增文件】的路径需要新建。修改已有文件时，diff 仅显示本篇变化，`+`、`-` 不能复制进源码。

| 标记 | 文件 | 职责 |
|---|---|---|
| 【新增文件】 | `backend/app/services/document_parser.py` | 文件名、内容检查与纯文本切片 |

## 3. 按顺序操作

终端执行位置：

```text
.
```

```bash
cd "."
```

本篇只运行纯函数，不调用 HTTP，也不需要登录令牌、MySQL 或 Redis。

### 步骤 1：【新增文件】 `backend/app/services/document_parser.py`

**编辑文件的完整地址：**

```text
./backend/app/services/document_parser.py
```

**文件职责与完整内容：** 先确认父目录已存在；本篇创建的是这个新文件，下面代码可整体保存。

```python
"""先支持 UTF-8 文本与 Markdown 的确定性解析和切片。"""

from app.core.failed_response import BusinessException

MAX_FILE_BYTES = 2 * 1024 * 1024
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
SUPPORTED_SUFFIXES = {".txt", ".md"}


def parse_text_document(filename: str, raw: bytes) -> tuple[str, str]:
    # 【新增】文件名只用于展示与去重，不把客户端路径当本机路径。
    safe_name = filename.replace("\\", "/").split("/")[-1].strip()
    suffix = "." + safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
    if not safe_name or len(safe_name) > 255 or suffix not in SUPPORTED_SUFFIXES:
        raise BusinessException(code=4001, message="本阶段只接受 .txt 或 .md 文件")
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise BusinessException(code=4001, message="文件必须非空且不超过 2 MB")
    try:
        content = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError as exc:
        raise BusinessException(code=4001, message="文件必须使用 UTF-8 编码") from exc
    if not content.strip():
        raise BusinessException(code=4001, message="文件没有可读取的文字")
    return safe_name, content


def split_text(content: str) -> list[str]:
    # 【新增】每段重叠 200 字符，减少边界处句子被切断的影响。
    chunks = []
    start = 0
    while start < len(content):
        end = min(start + CHUNK_SIZE, len(content))
        part = content[start:end]
        if part.strip():
            chunks.append(part)
        if end == len(content):
            break
        start = end - CHUNK_OVERLAP
    return chunks
```

**整体解释：** 解析器是文件进库前的验收台。它先从客户端给的名字里取安全的末段，仅接受 TXT/MD；再检查非空与 2 MB 上限，用 `utf-8-sig` 兼容 UTF-8 BOM，统一换行后拒绝全空白文字。任何失败都抛出已有 `BusinessException`，第 24 篇的上传路由会把它变成可读业务错误。切片器按 1000 字符一段、相邻段重叠 200 字符推进；重叠让边界附近的句子在至少一个片段中有上下文，但会使片段文字有重复，不能把切片数乘以 1000 当正文原长。方法本身既不访问数据库，也不调用模型，因而可以先单独验证。

## 4. 这些文件怎样连成一次请求

原始上传字节 → 文件名和大小检查 → UTF-8 解码及换行规范化 → `split_text` 生成片段。下一篇才把这些结果写到 `knowledge_documents` 和 `knowledge_chunks`；本篇运行解析函数不会新增数据库记录。

## 5. 运行与验证

先保存上述新文件，再在复刻 `backend` 目录直接运行；无需启动 Uvicorn。

```bash
cd "./backend"
uv run python - <<'PY'
from app.services.document_parser import parse_text_document, split_text
name, text = parse_text_document('demo.md', ('# 标题\n' + 'RAG' * 500).encode())
chunks = split_text(text)
print(name, len(text), len(chunks), [len(c) for c in chunks])
assert len(chunks) >= 2
assert chunks[0][-200:] == chunks[1][:200]
PY
```

**预期观察：** 输出文件名 `demo.md`，片段长度均不超过 1000，断言通过。可另外用非法后缀、空文件和非 UTF-8 字节确认业务错误；这一步只做纯函数检查，无需重启后端。

**排查顺序：** 若报 `ModuleNotFoundError: app`，确认当前目录是复刻 `backend`；若断言失败，检查 `CHUNK_SIZE`、`CHUNK_OVERLAP` 及 `start = end - CHUNK_OVERLAP`。若非法文件没有抛业务异常，检查解析函数的后缀、长度、UTF-8 和空白判断。本篇不涉及前端接口故障。

## 6. 本篇边界与下一篇

暂不解析 PDF、DOCX、PPTX 和图片；字符切片不会理解标题段落或语义边界。这些格式与能力要在后续章节明确新增，不能靠改扩展名假装支持。

第 24 篇让单个文本文件通过 HTTP 上传，并在一个事务里保存正文与切片。
