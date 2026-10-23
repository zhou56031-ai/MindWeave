"""演示数据种子：三条笔记 + demo-docs/ 下的文档。

为什么需要它：面试/演示时不能现场找资料，先把"可提问的语料"准备好，
之后所有问题都基于这套数据，回答和引用才稳定。

用法（在仓库根目录）：

    # 只检查账号与当前数据量，不写入任何内容
    DEMO_PASSWORD='你的口令' uv run --project backend python scripts/seed_demo.py --check

    # 写入演示数据（重复执行会产生重复笔记）
    DEMO_PASSWORD='你的口令' uv run --project backend python scripts/seed_demo.py

    # 换成别的账号或目录
    DEMO_PASSWORD='...' uv run --project backend python scripts/seed_demo.py \
        --username 456 --docs demo-docs
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

import httpx

NOTES = [
    (
        "Redis 缓存击穿",
        "缓存击穿是热点 key 过期瞬间，大量请求同时回源打到数据库。"
        "我的处理是两层：互斥锁重建（同一时刻只放一个请求回源），"
        "以及逻辑过期（读不阻塞，后台异步续期）。"
        "两者取舍：互斥锁实现简单但会短暂阻塞，逻辑过期读性能好但要容忍短暂旧值。",
        "study",
    ),
    (
        "FastAPI 请求级会话",
        "依赖注入里用 yield 提供 AsyncSession，请求结束自动关闭。"
        "注意不要在后台任务里复用请求会话：请求结束后连接已归还连接池。"
        "跨请求的写法是新建 AsyncSessionLocal()，并在 finally 里关闭。",
        "study",
    ),
    (
        "BM25 与向量检索的分工",
        "BM25 擅长专有名词、错误码、函数名这类需要精确匹配的查询；"
        "向量擅长同义改写、口语化描述。混合后应该用 RRF 融合名次，"
        "而不是把两种分数直接相加——两者量纲完全不同。",
        "study",
    ),
]

SUPPORTED = {".txt", ".md", ".pdf", ".docx", ".pptx"}


async def login(client: httpx.AsyncClient, username: str, password: str) -> str:
    response = await client.post("/user/login/", json={"username": username, "password": password})
    if response.status_code != 200:
        raise SystemExit(f"登录失败（HTTP {response.status_code}）：检查用户名与口令")
    return response.json()["token"]


async def counts(client: httpx.AsyncClient, headers: dict) -> tuple[int, int]:
    notes = await client.get("/note/list", params={"page": 1, "page_size": 1}, headers=headers)
    docs = await client.get("/knowledge/list", headers=headers)
    note_total = (notes.json().get("data") or {}).get("total_count", 0)
    doc_total = (docs.json().get("data") or {}).get("total_count", 0)
    return note_total, doc_total


async def main(args: argparse.Namespace) -> None:
    password = args.password or os.environ.get("DEMO_PASSWORD", "")
    if not password:
        raise SystemExit("缺少口令：用 DEMO_PASSWORD 环境变量传入，避免写进命令历史")

    async with httpx.AsyncClient(base_url=args.base, timeout=60) as client:
        token = await login(client, args.username, password)
        headers = {"Authorization": f"Bearer {token}"}
        note_total, doc_total = await counts(client, headers)
        print(f"账号 {args.username} 当前：{note_total} 篇笔记 / {doc_total} 份文档")

        if args.check:
            print("--check 模式：只读，不写入")
            return

        for title, content, category in NOTES:
            response = await client.post(
                "/note/create",
                headers=headers,
                json={"title": title, "content": content, "category": category},
            )
            print(f"笔记 {'OK ' if response.status_code == 200 else response.status_code} {title}")

        docs_dir = Path(args.docs)
        if not docs_dir.is_dir():
            print(f"跳过文档：{docs_dir} 不存在（放几份 PDF/Markdown 进去再跑）")
            return
        for path in sorted(docs_dir.iterdir()):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED:
                continue
            with path.open("rb") as handle:
                response = await client.post(
                    "/knowledge/add/single",
                    headers=headers,
                    files={"file": (path.name, handle, "application/octet-stream")},
                )
            print(f"文档 {'OK ' if response.status_code == 200 else response.status_code} {path.name}")

    print("完成。索引由 Worker 异步构建，稍等片刻再提问。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8100")
    parser.add_argument("--username", default="123")
    parser.add_argument("--password", default="")
    parser.add_argument("--docs", default="demo-docs")
    parser.add_argument("--check", action="store_true", help="只检查账号与数据量，不写入")
    asyncio.run(main(parser.parse_args()))
