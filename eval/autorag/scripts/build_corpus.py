"""把 eval/autorag/corpus 下的 Markdown 切成 AutoRAG corpus.parquet。"""
import importlib.util
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "backend" / "app" / "services" / "structured_chunks.py"
spec = importlib.util.spec_from_file_location("structured_chunks", MODULE)
chunker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chunker)
split_structured = chunker.split_structured

CORPUS = ROOT / "eval" / "autorag" / "corpus"
OUT = ROOT / "eval" / "autorag" / "data" / "corpus.parquet"

rows = []
for path in sorted(CORPUS.glob("*.md")):
    text = path.read_text(encoding="utf-8")
    for index, piece in enumerate(split_structured(text)):
        if len(piece.text.strip()) < 80:
            continue
        rows.append({
            "doc_id": f"pdf:{path.stem}:{index:03d}",
            "contents": piece.text,
            "metadata": {
                "last_modified_datetime": datetime.fromtimestamp(path.stat().st_mtime),
                "path": path.name,
                "page": piece.page,
                "chunk_index": index,
            },
            "path": path.name,
        })

frame = pd.DataFrame(rows).reset_index(drop=True)
OUT.parent.mkdir(parents=True, exist_ok=True)
frame.to_parquet(OUT, index=False)
print(f"chunks: {len(frame)} -> {OUT}")
