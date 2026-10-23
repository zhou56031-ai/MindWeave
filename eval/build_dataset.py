"""从 eval-bot 语料生成 50 条可答题 + 10 条不可答题。"""
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eval.common import DATASET  # noqa: E402

import asyncio  # noqa: E402

from sqlalchemy import select  # noqa: E402

from app.db.db_config import AsyncSessionLocal, async_engine  # noqa: E402
from app.models.knowledge_document import KnowledgeChunk, KnowledgeDocument  # noqa: E402
from app.models.user_model import User  # noqa: E402
from app.services.deepseek_client import deepseek_client  # noqa: E402

PROMPT = """请根据下面的片段，写一道中文问答题。
要求：问题能仅凭片段回答；不要问具体数值/日期；quote 是片段中连续出现的 15–40 字原文；
answer 用 1–2 句概括。只输出 JSON：{{"question":"...","quote":"...","answer":"..."}}

片段：
{content}
"""
NEGATIVES = [
    "火星上有没有液态水？",
    "如何用 Rust 实现一个 HTTP 服务器？",
    "请解释量子纠缠的贝尔不等式。",
    "2026 年世界杯冠军是谁？",
    "如何给猫做心肺复苏？",
    "请推荐三本适合初学者的日语教材。",
    "巴黎圣母院是哪一年重建完成的？",
    "如何计算黎曼 ζ 函数的非平凡零点？",
    "请写一首关于春天的五言绝句。",
    "股票明天会涨吗？",
]


def norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def parse(text: str):
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        return json.loads(text[i:j + 1])
    except json.JSONDecodeError:
        return None


async def main() -> None:
    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "eval-bot"))
        rows = (await db.execute(
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .where(KnowledgeDocument.user_id == user.uuid)
        )).all()
    await async_engine.dispose()

    rows = [(chunk, doc) for chunk, doc in rows if len(chunk.content) >= 120][:60]
    print("候选切片:", len(rows))

    async def generate(item):
        (chunk, doc), variant = item
        angle = "侧重操作步骤" if variant else "侧重概念与条件"
        try:
            raw = await deepseek_client.chat([
                {"role": "user", "content": PROMPT.format(content=chunk.content[:1600])
                 + f"\n本题{angle}。"},
            ], json_mode=True, max_tokens=400)
            data = parse(raw)
        except Exception:
            return None
        if not data:
            return None
        quote = (data.get("quote") or "").strip()
        question = (data.get("question") or "").strip()
        if not (8 <= len(question) <= 60) or not (12 <= len(quote) <= 60):
            return None
        if norm(quote) not in norm(chunk.content):
            return None
        return {
            "question": question, "quote": quote,
            "answer": (data.get("answer") or "").strip(),
            "doc_id": doc.id, "chunk_id": chunk.id, "filename": doc.filename,
            "answerable": True,
        }

    jobs = [(pair, variant) for pair in rows for variant in (0, 1)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        cases = [item for item in pool.map(lambda job: asyncio.run(generate(job)), jobs) if item]

    # 去重
    seen, unique = set(), []
    for item in cases:
        key = item["question"][:20]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    unique = unique[:50]
    for index, question in enumerate(NEGATIVES):
        unique.append({
            "question": question, "quote": "", "answer": "",
            "doc_id": None, "filename": "", "answerable": False,
        })
    for index, item in enumerate(unique, start=1):
        item["qid"] = f"e{index:03d}"

    DATASET.parent.mkdir(parents=True, exist_ok=True)
    DATASET.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in unique), encoding="utf-8")
    print("dataset:", len(unique), "answerable:", sum(x["answerable"] for x in unique))


if __name__ == "__main__":
    asyncio.run(main())
