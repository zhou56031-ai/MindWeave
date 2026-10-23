"""校验 60 条评测集：字段、引文可定位、正负样本比例、重复。"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eval.common import DATASET  # noqa: E402

import asyncio  # noqa: E402

from sqlalchemy import select  # noqa: E402

from app.db.db_config import AsyncSessionLocal, async_engine  # noqa: E402
from app.models.knowledge_document import KnowledgeChunk, KnowledgeDocument  # noqa: E402
from app.models.user_model import User  # noqa: E402


def norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


async def main() -> int:
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    errors = []
    if len(rows) < 60:
        errors.append(f"样本不足：{len(rows)} < 60")
    answerable = [row for row in rows if row.get("answerable")]
    negative = [row for row in rows if not row.get("answerable")]
    if len(negative) < 10:
        errors.append(f"不可答题不足：{len(negative)} < 10")
    if len({row["qid"] for row in rows}) != len(rows):
        errors.append("qid 重复")
    if len({row["question"] for row in rows}) != len(rows):
        errors.append("question 重复")

    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "eval-bot"))
        chunks = (await db.execute(
            select(KnowledgeChunk).join(KnowledgeDocument)
            .where(KnowledgeDocument.user_id == user.uuid)
        )).scalars().all()
    await async_engine.dispose()
    corpus = {chunk.id: chunk.content for chunk in chunks}

    for row in answerable:
        if not row.get("quote") or not row.get("chunk_id"):
            errors.append(f"{row['qid']} 缺少 quote/doc_id")
            continue
        text = corpus.get(row["chunk_id"])
        if text is None:
            errors.append(f"{row['qid']} chunk_id 不在语料中")
        elif norm(row["quote"]) not in norm(text):
            errors.append(f"{row['qid']} 引文定位失败")

    print(f"总数 {len(rows)}；可答 {len(answerable)}；不可答 {len(negative)}")
    print("校验结果:", "通过" if not errors else f"{len(errors)} 个问题")
    for error in errors[:20]:
        print(" -", error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
