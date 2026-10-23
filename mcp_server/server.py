"""最小 MCP stdio 服务：只暴露只读技能工具。

协议：JSON-RPC 2.0，一行一个请求；支持 initialize / tools/list / tools/call / ping。
用法：python mcp_server/server.py --selftest   # 自检
      python mcp_server/server.py              # 给 MCP 客户端用 stdin/stdout
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import skill_service  # noqa: E402

PROTOCOL = "2024-11-05"
TOOLS = [
    {
        "name": "list_skills",
        "description": "列出可用的本地技能名称",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "read_skill",
        "description": "按名称读取技能说明（只读）",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
    },
]


def _text(value: str) -> dict:
    return {"content": [{"type": "text", "text": value}], "isError": False}


def handle(request: dict) -> dict | None:
    """纯函数，便于单测；通知类请求返回 None。"""
    method = request.get("method")
    identifier = request.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        result = {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mindweave-skills", "version": "0.1.0"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            if name == "list_skills":
                result = _text("\n".join(skill_service.catalog()) or "（没有技能）")
            elif name == "read_skill":
                result = _text(skill_service.read(str(arguments.get("name", ""))))
            else:
                raise ValueError(f"未知工具：{name}")
        except ValueError as exc:
            return {"jsonrpc": "2.0", "id": identifier,
                    "error": {"code": -32602, "message": str(exc)}}
    else:
        return {"jsonrpc": "2.0", "id": identifier,
                "error": {"code": -32601, "message": f"未知方法：{method}"}}
    return {"jsonrpc": "2.0", "id": identifier, "result": result}


def selftest() -> int:
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "read_skill", "arguments": {"name": "rag-basics"}}},
    ]
    for request in requests:
        response = handle(request)
        assert response and response.get("result") is not None, response
    names = [tool["name"] for tool in handle(requests[1])["result"]["tools"]]
    assert names == ["list_skills", "read_skill"], names
    print("MCP selftest ok:", names)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            response = handle(json.loads(line))
        except json.JSONDecodeError:
            response = {"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32700, "message": "JSON 解析失败"}}
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
