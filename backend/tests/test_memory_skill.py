"""记忆/技能的只读与审批边界。"""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agent.loop_tools import dispatch
from app.agent.tool_schemas import ToolChoice
from app.agent.tools import write_proposal
from app.services import skill_service
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "mcp_server"))
import server as mcp_server


class SkillTests(unittest.TestCase):
    def test_catalog_contains_builtin_skills(self):
        self.assertIn("rag-basics", skill_service.catalog())

    def test_read_returns_content(self):
        self.assertIn("召回", skill_service.read("rag-basics"))

    def test_rejects_traversal(self):
        with self.assertRaises(ValueError):
            skill_service.read("../secret")


class ProposalTests(unittest.TestCase):
    def test_remember_is_a_proposal_not_a_direct_write(self):
        proposal = write_proposal(ToolChoice(tool="remember", arguments={"content": "偏好简洁回答"}))
        self.assertEqual(proposal["tool"], "remember")
        self.assertIn("偏好简洁回答", proposal["description"])


class DispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_load_skill_is_read_only(self):
        store = SimpleNamespace(user_id="u1")
        result = await dispatch("load_skill", {"name": "rag-basics"}, store)
        self.assertIn("召回", result["result"])


class McpTests(unittest.TestCase):
    def test_initialize_and_list(self):
        init = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertEqual(init["result"]["protocolVersion"], "2024-11-05")
        listed = mcp_server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual([tool["name"] for tool in listed["result"]["tools"]],
                         ["list_skills", "read_skill"])

    def test_call_read_skill(self):
        response = mcp_server.handle({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "read_skill", "arguments": {"name": "rag-basics"}},
        })
        self.assertIn("召回", response["result"]["content"][0]["text"])

    def test_unknown_tool_is_error(self):
        response = mcp_server.handle({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "rm_rf", "arguments": {}},
        })
        self.assertEqual(response["error"]["code"], -32602)


if __name__ == "__main__":
    unittest.main()
