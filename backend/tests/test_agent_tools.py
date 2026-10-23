"""第 48 章工具白名单与写入提案边界。"""

import unittest

from pydantic import ValidationError

from app.agent.run_store import approval_payload
from app.agent.tool_schemas import CreateNoteArgs, ToolChoice
from app.agent.tools import write_proposal


class AgentToolTests(unittest.TestCase):
    def test_rejects_tool_outside_whitelist(self):
        with self.assertRaises(ValidationError):
            ToolChoice.model_validate({
                "tool": "delete_everything",
                "arguments": {},
            })

    def test_create_note_proposal_does_not_create_data(self):
        proposal = write_proposal(ToolChoice(
            tool="create_note",
            arguments={"title": "  审批练习  ", "content": "正文"},
        ))

        self.assertEqual(proposal["arguments"]["title"], "审批练习")
        self.assertEqual(proposal["tool"], "create_note")
        self.assertIn("审批练习", proposal["description"])

    def test_proposal_payload_matches_frontend_contract(self):
        payload = approval_payload({
            "tool": "create_note",
            "arguments": {"title": "标题", "content": "正文"},
            "description": "创建笔记：标题",
        })

        self.assertEqual(payload["action_requests"][0]["name"], "create_note")
        self.assertEqual(
            payload["review_configs"][0]["allowed_decisions"],
            ["approve", "reject"],
        )

    def test_create_note_rejects_blank_title_after_trim(self):
        with self.assertRaises(ValidationError):
            CreateNoteArgs(title="   ", content="正文")


if __name__ == "__main__":
    unittest.main()
