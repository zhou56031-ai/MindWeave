"""原生工具调用到已有业务的适配层。"""
from fastapi import HTTPException
from pydantic import ValidationError
from app.agent.loop_protocol import REGISTRY
from app.agent.tool_schemas import ToolChoice
from app.agent.tools import read_tool, write_proposal
from app.db.db_config import AsyncSessionLocal
from app.rag.agentic_service import collect_evidence
from app.services import skill_service
from app.services.chat_context import serialize
from app.core.agent_trace import emit, text_info


async def dispatch(name: str, arguments: dict, store) -> dict:
    if name not in REGISTRY:
        return {"result": {"error": "未知工具"}}
    try:
        args = REGISTRY[name][0].model_validate(arguments).model_dump()
        if name == "compact":
            return {"result": {"status": "已请求整理旧上下文"}, "compact": True}
        if name == "read_artifact":
            return {"result": await store.read_artifact(**args)}
        if name == "load_skill":
            return {"result": skill_service.read(args["name"])}
        if name == "search_rag":
            async with AsyncSessionLocal() as db:
                hits, context, answerability, used_web = await collect_evidence(
                    db, store.user_id, args["query"],
                )
            return {"result": {
                "context": context, "answerability": answerability.model_dump(),
                "has_web_evidence": used_web,
                "sources": [h.model_dump() for h in hits],
            }, "evidence": [h.model_dump() for h in hits]}
        choice = ToolChoice(tool=name, arguments=args)
        proposal = write_proposal(choice)
        if proposal:
            return {"proposal": proposal}
        async with AsyncSessionLocal() as db:
            result = await read_tool(db, store.user_id, choice)
        return {"result": result or "工具未返回内容"}
    except ValidationError:
        return {"result": {"error": "参数不符合工具 schema，请纠正"}}
    except HTTPException as exc:
        return {"result": {"error": str(exc.detail), "status": exc.status_code}}


async def pack_result(store, name: str, result) -> str:
    raw = result if isinstance(result, str) else serialize(result)
    artifact_id = await store.archive("tool", raw)
    emit("tool.archived", tool=name, artifact_id=artifact_id, original=text_info(raw))
    # 读回已经按 2000 字符分页；再次截断会丢失 next_offset 和原文。
    if name == "search_rag" and isinstance(result, dict):
        # 【修改】使用完整的有界 context，避免统一短预览丢掉后续证据。
        preview = serialize({
            "context": result.get("context", ""),
            "answerability": result.get("answerability", {}),
            "has_web_evidence": result.get("has_web_evidence", False),
        })
    else:
        preview = raw if name == "read_artifact" else raw[:2500]
    # 只缩减模型输入；完整结果已持久保存，恢复工具每页 2000 字符。
    return serialize({
        "tool": name, "artifact_id": artifact_id,
        "preview": preview, "truncated": len(preview) < len(raw),
        "hint": "需要原文时调用 read_artifact，offset 从 0 开始",
    })
