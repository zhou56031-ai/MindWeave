"""文本解析和切片，以及所有上传共用的文件大小边界。"""

from app.core.failed_response import BusinessException

# 【修改】所有上传路由与解析服务共用这一字节上限。
MAX_FILE_BYTES = 10 * 1024 * 1024
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
        raise BusinessException(code=4001, message="文件必须非空且不超过 10 MB")
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
