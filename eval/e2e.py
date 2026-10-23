"""端到端抽检：20 条可答 + 10 条不可答，统计引用捏造与拒答。"""
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eval.common import DATASET, RESULTS  # noqa: E402

from sqlalchemy import select  # noqa: E402

from app.db.db_config import AsyncSessionLocal, async_engine  # noqa: E402
from app.models.user_model import User  # noqa: E402
from app.rag.hybrid_retrieval import search  # noqa: E402
from app.services.deepseek_client import deepseek_client  # noqa: E402

PROMPT = """只依据下面的资料回答问题。
- 每个结论后用 [编号] 标注来源，编号必须是 1 到 {count}；
- 资料不足时直接回答“资料不足，无法回答”，不要编造；
- 用中文，2 到 4 句。

资料：
{context}

问题：{question}
"""
REFUSAL = re.compile(r"(资料不足|无法回答|没有提到|未提及|不知道|无法确定)")


async def main() -> None:
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    answerable = [row for row in rows if row["answerable"]][:20]
    negatives = [row for row in rows if not row["answerable"]][:10]
    details = []
    fabricated = 0
    refusals = 0
    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "eval-bot"))
        for row in answerable + negatives:
            hits = await search(db, user.uuid, row["question"])
            evidence = hits[:5]
            context = "\n\n".join(f"[{index + 1}] {hit.snippet[:500]}"
                                  for index, hit in enumerate(evidence))
            try:
                answer = await deepseek_client.chat([
                    {"role": "user", "content": PROMPT.format(
                        count=len(evidence), context=context, question=row["question"])},
                ], max_tokens=400)
            except Exception as exc:
                answer = f"<error:{type(exc).__name__}>"
            citations = [int(value) for value in re.findall(r"\[(\d+)\]", answer)]
            bad = [value for value in citations if value < 1 or value > len(evidence)]
            is_refusal = bool(REFUSAL.search(answer))
            if bad:
                fabricated += 1
            if not row["answerable"] and is_refusal:
                refusals += 1
            details.append({
                "qid": row["qid"], "answerable": row["answerable"],
                "answer": answer, "citations": citations,
                "invalid_citations": bad, "refused": is_refusal,
            })
    await async_engine.dispose()

    summary = {
        "answerable": len(answerable),
        "negative": len(negatives),
        "fabricated_citations": fabricated,
        "refusal_accuracy": round(refusals / max(len(negatives), 1), 4),
        "details": details,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "e2e.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"端到端：{len(answerable)} 可答 + {len(negatives)} 不可答 | "
          f"引用捏造 {fabricated} 条 | 拒答正确 {refusals}/{len(negatives)}")


if __name__ == "__main__":
    asyncio.run(main())
