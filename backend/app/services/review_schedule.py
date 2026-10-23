"""回顾间隔规则；数据库读写留在服务层。"""
from datetime import UTC, datetime, timedelta

INTERVAL_DAYS = (1, 2, 4, 7, 15, 30)


def utc_naive_now() -> datetime:
    """MySQL DATETIME 本阶段统一存 UTC 时刻，不带时区标记。"""
    return datetime.now(UTC).replace(tzinfo=None)


def interval_for_completed_count(completed_count: int) -> int:
    if completed_count < 0:
        raise ValueError("回顾次数不能为负")
    return INTERVAL_DAYS[min(completed_count, len(INTERVAL_DAYS) - 1)]#这个是为了防止拿到超过 INTERVAL_DAYS 长度的索引，取最后一个元素


def first_due_at(now: datetime) -> datetime:
    return now + timedelta(days=INTERVAL_DAYS[0])
