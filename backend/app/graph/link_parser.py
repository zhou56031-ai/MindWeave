"""从 Markdown 笔记提取 [[双链]] 目标标题。"""

import re

LINK = re.compile(r"\[\[([^\]\n]{1,200})\]\]")


def parse_links(content: str) -> list[str]:
    result = []
    for match in LINK.finditer(content or ""):
        title = match.group(1).strip()
        if title and title not in result:
            result.append(title)
    return result[:50]
