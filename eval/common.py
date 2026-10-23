"""eval 公共路径与后端加载。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

EVAL_USER = "eval-bot"
DATASET = ROOT / "eval" / "dataset" / "test.jsonl"
RESULTS = ROOT / "eval" / "results"
CORPUS_FILES = [
    ROOT / "demo-docs" / "缓存与检索.md",
    ROOT / "docs" / "design-system.md",
    ROOT / "docs" / "AI-Agent功能全景说明.md",
]
