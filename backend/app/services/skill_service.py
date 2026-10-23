"""只读技能目录：名称白名单 + 目录逃逸防护。"""
import re
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[3] / "skills"
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
MAX_CHARS = 20_000


def catalog() -> list[str]:
    if not SKILLS_DIR.is_dir():
        return []
    return sorted(path.stem for path in SKILLS_DIR.glob("*.md") if NAME.match(path.stem))


def read(name: str) -> str:
    if not NAME.match(name or ""):
        raise ValueError("技能名不合法")
    path = (SKILLS_DIR / f"{name}.md").resolve()
    if SKILLS_DIR.resolve() not in path.parents or not path.is_file():
        raise ValueError("技能不存在")
    return path.read_text(encoding="utf-8")[:MAX_CHARS]
