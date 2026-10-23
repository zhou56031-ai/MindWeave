"""聚合 agent_traces：P50/P95、token、成本、中止率、工具失败率。

用法（仓库根目录）：
    uv run --project backend python scripts/metrics_report.py --days 7
    uv run --project backend python scripts/metrics_report.py --days 7 --json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import text  # noqa: E402

from app.db.db_config import AsyncSessionLocal, async_engine  # noqa: E402


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * ratio)))
    return ordered[index]


def summarize(rows: list[dict]) -> dict:
    durations, input_tokens, output_tokens = [], [], []
    statuses: dict[str, int] = {}
    stopped = tool_calls = tool_failures = fallbacks = 0
    for row in rows:
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1
        durations.append(float(row["duration_ms"]))
        payload = json.loads(row["payload"] or "{}")
        for event in payload.get("events", []):
            name, data = event.get("name", ""), event.get("data", {})
            if name == "request.usage":
                input_tokens.append(int(data.get("input_tokens") or 0))
                output_tokens.append(int(data.get("output_tokens") or 0))
            elif name == "agent.loop_stopped":
                stopped += 1
            elif name == "agent.tool.end":
                tool_calls += 1
                if data.get("status") not in (None, "ok") or data.get("business_error"):
                    tool_failures += 1
            elif name == "rag.fallback":
                fallbacks += 1

    price_in = float(os.getenv("DEEPSEEK_PRICE_INPUT", "0"))
    price_out = float(os.getenv("DEEPSEEK_PRICE_OUTPUT", "0"))
    cost = (sum(input_tokens) * price_in + sum(output_tokens) * price_out) / 1_000_000
    requests = len(rows) or 1
    return {
        "requests": len(rows),
        "statuses": statuses,
        "duration_ms_p50": round(percentile(durations, 0.50), 1),
        "duration_ms_p95": round(percentile(durations, 0.95), 1),
        "avg_input_tokens": round(sum(input_tokens) / requests, 1),
        "avg_output_tokens": round(sum(output_tokens) / requests, 1),
        "total_cost": round(cost, 4),
        "avg_cost": round(cost / requests, 4),
        "abort_rate": round(stopped / requests, 4),
        "tool_calls": tool_calls,
        "tool_failure_rate": round(tool_failures / tool_calls, 4) if tool_calls else 0.0,
        "fallbacks": fallbacks,
    }


async def load(days: int) -> list[dict]:
    since = datetime.now() - timedelta(days=days)
    async with AsyncSessionLocal() as db:
        result = await db.execute(text(
            "SELECT status, duration_ms, payload FROM agent_traces "
            "WHERE created_at >= :since ORDER BY created_at DESC"
        ), {"since": since})
        rows = [dict(row._mapping) for row in result]
    await async_engine.dispose()
    return rows


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    summary = summarize(await load(args.days))
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    print(f"近 {args.days} 天请求数：{summary['requests']}")
    print(f"P50 / P95：{summary['duration_ms_p50']} ms / {summary['duration_ms_p95']} ms")
    print(f"平均 token：输入 {summary['avg_input_tokens']}，输出 {summary['avg_output_tokens']}")
    print(f"平均成本：￥{summary['avg_cost']}（总 ￥{summary['total_cost']}）")
    print(f"中止率：{summary['abort_rate']:.2%}")
    print(f"工具调用：{summary['tool_calls']}，失败率 {summary['tool_failure_rate']:.2%}")
    print(f"MySQL 降级次数：{summary['fallbacks']}")


if __name__ == "__main__":
    asyncio.run(main())
