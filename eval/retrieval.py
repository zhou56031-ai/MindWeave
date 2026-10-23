"""检索评测：Recall@3/5、MRR@5，按来源文档分组。"""
import asyncio
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eval.common import DATASET, RESULTS  # noqa: E402

from sqlalchemy import select  # noqa: E402

from app.db.db_config import AsyncSessionLocal, async_engine  # noqa: E402
from app.graph.neo4j_client import graph_driver  # noqa: E402
from app.models.user_model import User  # noqa: E402
from app.rag.hybrid_retrieval import search  # noqa: E402


def norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


async def main() -> None:
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    answerable = [row for row in rows if row["answerable"]]
    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "eval-bot"))
        per_file = defaultdict(lambda: [0, 0, 0, 0.0])
        hits3 = hits5 = 0
        reciprocal = 0.0
        details = []
        for row in answerable:
            hits = await search(db, user.uuid, row["question"])
            ids = [hit.chunk_id for hit in hits[:5] if hit.chunk_id]
            records = (await graph_driver().execute_query(
                "MATCH (c:Chunk {user_id:$u}) WHERE c.id IN $ids "
                "RETURN c.id AS id, c.text AS text", u=user.uuid, ids=ids,
            )).records
            texts = {record["id"]: record["text"] for record in records}
            gold = norm(row["quote"])
            rank = next((index + 1 for index, cid in enumerate(ids) if gold in norm(texts.get(cid, ""))), 0)
            hits3 += int(0 < rank <= 3)
            hits5 += int(0 < rank <= 5)
            reciprocal += (1.0 / rank) if rank else 0.0
            bucket = per_file[row["filename"]]
            bucket[0] += 1
            bucket[1] += int(0 < rank <= 3)
            bucket[2] += int(0 < rank <= 5)
            bucket[3] += (1.0 / rank) if rank else 0.0
            details.append({"qid": row["qid"], "rank": rank, "question": row["question"]})
    await async_engine.dispose()

    total = len(answerable)
    summary = {
        "total": total,
        "recall@3": round(hits3 / total, 4),
        "recall@5": round(hits5 / total, 4),
        "mrr@5": round(reciprocal / total, 4),
        "per_file": {
            name: {"n": value[0], "recall@3": round(value[1] / value[0], 4),
                   "recall@5": round(value[2] / value[0], 4),
                   "mrr@5": round(value[3] / value[0], 4)}
            for name, value in per_file.items()
        },
        "details": details,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "retrieval.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"检索：{total} 条 | Recall@3 {summary['recall@3']} | Recall@5 {summary['recall@5']} | MRR@5 {summary['mrr@5']}")
    for name, value in summary["per_file"].items():
        print(f"  {value['n']:>2} 条  R@3 {value['recall@3']:.2f}  R@5 {value['recall@5']:.2f}  {name}")


if __name__ == "__main__":
    asyncio.run(main())
