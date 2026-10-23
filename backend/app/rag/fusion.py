"""多路召回融合：RRF 名次分、来源配额、按 chunk id 去重。

跨源分数不可比（向量余弦、BM25 打分、图路径权重量纲不同），
因此这里只使用名次；配额用于防止某一路挤占全部候选。
"""
from __future__ import annotations

from typing import Iterable, Optional

RRF_SCALE = 100000
RRF_K = 60
_LUCENE_SPECIALS = set('+-&|!(){}[]^"~*?:\\/')


def rrf_points(rank: int) -> int:
    """名次越靠前分越高；与旧实现的 int(100000/(60+rank)) 保持一致。"""
    return RRF_SCALE // (RRF_K + rank)


def escape_lucene(text: str) -> str:
    """转义 Lucene 查询语法字符，避免 queryNodes 解析失败导致整条链路降级。"""
    return "".join(f"\\{ch}" if ch in _LUCENE_SPECIALS else ch for ch in text)


def fuse(
    sources: Iterable[tuple[str, list[dict]]],
    *,
    limit: int,
    quotas: Optional[dict[str, int]] = None,
) -> list[tuple[int, dict]]:
    """按来源顺序累加 RRF 分，返回 [(score, row)]。

    row 必须含 "id"；同名 id 只保留一份，并在 sources 里记录来源。
    quotas[name] 为该路进入融合的最大条数（None 表示不限制）。
    """
    quotas = quotas or {}
    merged: dict[str, dict] = {}
    order = 0
    for name, rows in sources:
        cap = quotas.get(name)
        for rank, row in enumerate(rows[:cap] if cap else rows, start=1):
            key = str(row["id"])
            point = rrf_points(rank)
            current = merged.get(key)
            if current is None:
                merged[key] = {
                    "score": point,
                    "row": dict(row),
                    "sources": [name],
                    "order": order,
                }
                order += 1
            else:
                current["score"] += point
                if name not in current["sources"]:
                    current["sources"].append(name)

    ranked = sorted(
        merged.values(),
        key=lambda item: (-item["score"], item["order"]),
    )[:limit]
    return [(item["score"], {**item["row"], "sources": item["sources"]}) for item in ranked]
