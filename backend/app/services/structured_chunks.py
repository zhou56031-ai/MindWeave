"""按标题、段落与代码围栏组织切片，长块才使用重叠窗口。"""
import re
from dataclasses import dataclass

CHUNK_VERSION = "structure-v2"
BODY_LIMIT = 900
OVERLAP = 120


@dataclass
class IndexPiece:
    text: str
    page: int | None = None
    section: str = ""


def split_structured(text: str, page: int | None = None) -> list[IndexPiece]:
    sections = []
    headings = []
    block = []
    code = False

    def flush_block():
        if block:
            sections.append((" > ".join(headings), "\n".join(block).strip()))
            block.clear()

    for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        if line.lstrip().startswith("```"):
            code = not code
        title = re.match(r"^(#{1,6})\s+(.+)$", line) if not code else None
        if title:
            flush_block()
            level = len(title.group(1))
            headings[:] = headings[:level - 1]
            headings.append(title.group(2).strip()[:80])
            block.append(line)
        elif not line.strip() and not code:
            flush_block()
        else:
            block.append(line)
    flush_block()

    result = []
    pending = ""
    current_section = ""

    def save():
        nonlocal pending
        if pending.strip():
            section = current_section[:180]
            prefix = f"[章节] {section}\n" if section else ""
            result.append(IndexPiece(prefix + pending.strip(), page, section))
        pending = ""

    for section, paragraph in sections:
        if not paragraph:
            continue
        if section != current_section:
            save()
            current_section = section
        if len(paragraph) > BODY_LIMIT:
            save()
            start = 0
            while start < len(paragraph):
                pending = paragraph[start:start + BODY_LIMIT]
                save()
                if start + BODY_LIMIT >= len(paragraph):
                    break
                start += BODY_LIMIT - OVERLAP
        else:
            joined = (pending + "\n\n" + paragraph).strip()
            if len(joined) > BODY_LIMIT:
                save()
                pending = paragraph
            else:
                pending = joined
    save()
    return result


def section_from_text(text: str) -> str:
    first = text.splitlines()[0] if text else ""
    return first.removeprefix("[章节] ")[:180] if first.startswith("[章节] ") else ""

def parent_map(pieces: list[IndexPiece], limit: int = 1800) -> list[tuple[str, str]]:
    """为每个子块标注父块：同章节连续子块合成一个父块，超过 limit 强制切组。

    返回与 pieces 等长的 [(parent_id, parent_text)]；父子块都留在同一次索引里，
    检索命中子块后由 evidence_selection 回填父块。
    """
    if not pieces:
        return []
    groups: list[list[IndexPiece]] = []
    current: list[IndexPiece] = []
    size = 0

    def flush() -> None:
        nonlocal current, size
        if current:
            groups.append(current)
        current, size = [], 0

    for piece in pieces:
        piece_size = len(piece.text)
        if current and (
            piece.section != current[-1].section or size + piece_size > limit
        ):
            flush()
        current.append(piece)
        size += piece_size
    flush()

    mapping: list[tuple[str, str]] = []
    for index, group in enumerate(groups):
        parent_id = f"p{index}"
        parent_text = "\n\n".join(item.text for item in group)
        mapping.extend([(parent_id, parent_text)] * len(group))
    return mapping
