import json
import unittest
from types import SimpleNamespace

from usr.plugins.a0_hindsight.helpers import hindsight_helper as h


class History:
    def __init__(self, messages):
        self._messages = messages

    def output(self):
        return self._messages


class HindsightHelperTests(unittest.TestCase):
    def agent(self, messages, context_id="ctx-test"):
        return SimpleNamespace(
            history=History(messages),
            context=SimpleNamespace(id=context_id),
            agent_name="A0",
            config=SimpleNamespace(profile="default"),
        )

    def response_json(self, text):
        return json.dumps({
            "thoughts": ["internal reasoning that must not be retained"],
            "headline": "Responding",
            "tool_name": "response",
            "tool_args": {"text": text},
        })

    def tool_json(self):
        return json.dumps({
            "thoughts": ["try a shell command"],
            "headline": "Running command",
            "tool_name": "code_execution_tool",
            "tool_args": {"runtime": "terminal", "code": "echo test"},
        })

    def scheduled_prompt(self):
        return "## Task:\nRun the email poller script and report the result briefly."

    def test_chatlog_keeps_user_text_and_final_answer_only(self):
        agent = self.agent([
            {"ai": False, "content": "Hallo"},
            {"ai": True, "content": self.tool_json()},
            {"ai": True, "content": self.response_json("Final answer")},
        ])

        chatlog = h.build_chatlog(agent)

        self.assertEqual([entry["role"] for entry in chatlog], ["user", "assistant"])
        self.assertEqual(chatlog[0]["content"], "Hallo")
        self.assertEqual(chatlog[1]["content"], "Final answer")
        self.assertNotIn("internal reasoning", json.dumps(chatlog))
        self.assertNotIn("code_execution_tool", json.dumps(chatlog))

    def test_chatlog_skips_scheduled_task_turn(self):
        agent = self.agent([
            {"ai": False, "content": "Before"},
            {"ai": True, "content": self.response_json("Before answer")},
            {"ai": False, "content": self.scheduled_prompt()},
            {"ai": True, "content": self.response_json("Scheduled result")},
            {"ai": False, "content": "After"},
            {"ai": True, "content": self.response_json("After answer")},
        ])

        chatlog = h.build_chatlog(agent)
        contents = [entry["content"] for entry in chatlog]

        self.assertEqual(contents, ["Before", "Before answer", "After", "After answer"])

    def test_scheduled_task_fallback_is_stable(self):
        context = SimpleNamespace(id="ctx-test")
        task1 = h.get_scheduled_task_for_text(context, self.scheduled_prompt())
        task2 = h.get_scheduled_task_for_text(context, self.scheduled_prompt())

        self.assertIsNotNone(task1)
        self.assertEqual(task1["uuid"], task2["uuid"])
        self.assertTrue(task1["uuid"].startswith("prompt-"))

    def test_secret_redaction_covers_common_tokens(self):
        text = h._redact_secrets(
            "api_key=abc123456789 password:supersecret am_abcdefghijklmnopqrstuvwxyz "
            "\"client_secret\": \"very-secret-value\" export HERMES_TOKEN=tok_123456789 "
            "whsec_abcdefghijklmnopqrstuvwxyz"
        )

        self.assertNotIn("abc123456789", text)
        self.assertNotIn("supersecret", text)
        self.assertNotIn("am_abcdefghijklmnopqrstuvwxyz", text)
        self.assertNotIn("very-secret-value", text)
        self.assertNotIn("tok_123456789", text)
        self.assertNotIn("whsec_abcdefghijklmnopqrstuvwxyz", text)
        self.assertIn("[REDACTED]", text)

    def test_metadata_includes_shared_bank_source_fields(self):
        context = SimpleNamespace(id="ctx-test")
        agent = self.agent([], context_id="ctx-test")

        metadata = h.build_metadata(context, agent, 2)

        self.assertEqual(metadata["framework"], "agent-zero")
        self.assertEqual(metadata["platform"], "agent-zero")
        self.assertEqual(metadata["source"], "agent-zero")
        self.assertEqual(metadata["agent_identity"], "A0")
        self.assertEqual(metadata["session_id"], "ctx-test")
        self.assertEqual(metadata["chat_id"], "ctx-test")


if __name__ == "__main__":
    unittest.main()
