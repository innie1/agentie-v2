import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import agent_access, agent_registry, capability_preflight


LEGACY_INFO = {
    "tools": [
        {"name": "list_inboxes"},
        {"name": "list_messages"},
        {"name": "search_messages"},
        {"name": "send_message"},
    ]
}
CURRENT_INFO = {
    "tools": [
        {"name": "list_inboxes", "input_schema": {"properties": {"limit": {}}}},
        {"name": "list_threads", "input_schema": {"properties": {"inboxId": {}, "limit": {}, "senders": {}, "recipients": {}, "subject": {}}}},
        {"name": "get_thread", "input_schema": {"properties": {"inboxId": {}, "threadId": {}}}},
        {"name": "reply_to_message", "input_schema": {"properties": {"inboxId": {}, "messageId": {}, "text": {}}}},
        {"name": "send_message", "input_schema": {"properties": {"inboxId": {}, "to": {}, "subject": {}, "text": {}}}},
    ]
}


class EmailAgentsRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.workspace_patch = patch.object(capability_preflight, "WORKSPACE", root)
        self.agent_workspace_patch = patch.object(agent_registry, "WORKSPACE", root)
        self.agent_file_patch = patch.object(agent_registry, "AGENTS_FILE", root / "agents.json")
        self.workspace_patch.start(); self.agent_workspace_patch.start(); self.agent_file_patch.start()
        self.ben = agent_registry.create_agent("Ben", "Sales & Outreach", "general", purpose="Increase qualified sales")["agent"]
        self.ben = agent_registry.update_agent_profile(self.ben["id"], company_identity="COAN Industries", goal="Increase sales")
        self.mira = agent_registry.create_agent("Mira", "Market Research Analyst", "research", purpose="Research markets and competitors")["agent"]
        self.ben_session = f"{self.ben['session_prefix']}main"
        capability_preflight._save_agentmail_settings({"inbox_id": "global_inbox", "notification_email": "owner@example.com"})

    def tearDown(self):
        self.agent_file_patch.stop(); self.agent_workspace_patch.stop(); self.workspace_patch.stop()
        self.temp.cleanup()

    def test_agent_specific_inbox_overrides_global_without_breaking_global_default(self):
        result = capability_preflight._agentmail_config("Set my AgentMail inbox to ben_inbox", self.ben_session)
        self.assertIn("Ben", result["message"])
        stored = capability_preflight._load_agentmail_settings()
        self.assertEqual(stored["inbox_id"], "global_inbox")
        self.assertEqual(stored["agents"][self.ben["id"]]["inbox_id"], "ben_inbox")
        self.assertEqual(capability_preflight._scoped_agentmail_settings(self.ben_session)["inbox_id"], "ben_inbox")
        self.assertEqual(capability_preflight._scoped_agentmail_settings(None)["inbox_id"], "global_inbox")

    def test_outbound_email_uses_persistent_ai_employee_identity_signature(self):
        capability_preflight._agentmail_config("Set my AgentMail inbox to ben_inbox", self.ben_session)
        tool, args = capability_preflight._agentmail_choice(
            "Email client@example.com subject Follow-up saying Thanks for your order", LEGACY_INFO, self.ben_session
        )
        self.assertEqual(tool, "send_message")
        self.assertEqual(args["inboxId"], "ben_inbox")
        self.assertIn("Thanks for your order", args["text"])
        self.assertIn("Ben", args["text"])
        self.assertIn("AI Sales & Outreach Agent", args["text"])
        self.assertIn("COAN Industries", args["text"])

    def test_default_non_agent_email_behavior_remains_backward_compatible(self):
        tool, args = capability_preflight._agentmail_choice("Email me saying the build is complete", LEGACY_INFO, None)
        self.assertEqual(tool, "send_message")
        self.assertEqual(args["inboxId"], "global_inbox")
        self.assertEqual(args["to"], ["owner@example.com"])
        self.assertEqual(args["text"], "the build is complete")

    def test_search_email_is_not_misclassified_as_send(self):
        tool, args = capability_preflight._agentmail_choice("Search my email for invoice", LEGACY_INFO, self.ben_session)
        self.assertEqual(tool, "search_messages")
        self.assertEqual(args["q"], "invoice")

    def test_current_agentmail_thread_catalog_is_supported_dynamically(self):
        capability_preflight._agentmail_config("Set my AgentMail inbox to ben_inbox", self.ben_session)
        tool, args = capability_preflight._agentmail_choice("Search my email for invoice", CURRENT_INFO, self.ben_session)
        self.assertEqual(tool, "list_threads")
        self.assertEqual(args["inboxId"], "ben_inbox")
        self.assertEqual(args["subject"], ["invoice"])
        tool, args = capability_preflight._agentmail_choice("Open thread th_123", CURRENT_INFO, self.ben_session)
        self.assertEqual(tool, "get_thread")
        self.assertEqual(args, {"inboxId": "ben_inbox", "threadId": "th_123"})

    def test_reply_uses_same_agent_identity_and_requires_real_reply_tool(self):
        capability_preflight._agentmail_config("Set my AgentMail inbox to ben_inbox", self.ben_session)
        tool, args = capability_preflight._agentmail_choice("Reply to message msg_123 saying I will follow up tomorrow", CURRENT_INFO, self.ben_session)
        self.assertEqual(tool, "reply_to_message")
        self.assertEqual(args["messageId"], "msg_123")
        self.assertIn("AI Sales & Outreach Agent", args["text"])

    def test_incoming_sales_message_routes_to_existing_sales_agent(self):
        payload = {"threads": [{"threadId": "th_1", "subject": "New customer lead wants a quote", "from": "buyer@example.com", "preview": "Please follow up on this order."}]}
        result = {"message": "ok", "card": {"type": "note", "title": "MCP", "content": json.dumps(payload)}}
        formatted = capability_preflight.finalize_agentmail_result("list_threads", {"inboxId": "ben_inbox"}, result, self.ben_session)
        self.assertEqual(formatted["card"]["title"], "Email · Inbox")
        self.assertIn("Routed to Ben (Sales & Outreach)", formatted["card"]["content"])

    def test_ambiguous_incoming_message_is_not_falsely_routed(self):
        payload = {"threads": [{"threadId": "th_2", "subject": "Hello", "from": "person@example.com", "preview": "Just checking in."}]}
        result = {"message": "ok", "card": {"type": "note", "title": "MCP", "content": json.dumps(payload)}}
        formatted = capability_preflight.finalize_agentmail_result("list_threads", {"inboxId": "ben_inbox"}, result, self.ben_session)
        self.assertNotIn("Routed to", formatted["card"]["content"])

    def test_email_history_is_local_bounded_and_agent_scoped(self):
        payload = {"threads": [{"threadId": "th_3", "subject": "Customer order", "from": "buyer@example.com", "preview": "Need a quote"}]}
        raw = {"message": "ok", "card": {"type": "note", "title": "MCP", "content": json.dumps(payload)}}
        capability_preflight.finalize_agentmail_result("list_threads", {"inboxId": "ben_inbox"}, raw, self.ben_session)
        history = capability_preflight._load_agentmail_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["agent_id"], self.ben["id"])
        card = capability_preflight._history_card(self.ben_session)
        self.assertIn("Customer order", card["card"]["content"])
        self.assertIn("Ben", card["card"]["title"])

    def test_natural_email_uses_existing_per_agent_mcp_permission_detector(self):
        with patch.object(agent_access, "list_servers", return_value=[{"name": "agentmail"}]):
            self.assertEqual(agent_access._mentioned_mcp("Check my email"), "agentmail")
            self.assertEqual(agent_access._mentioned_mcp("Email client@example.com saying hello"), "agentmail")
            self.assertIsNone(agent_access._mentioned_mcp("Show email history"))
            self.assertIsNone(agent_access._mentioned_mcp("Set my AgentMail inbox to inbox_123"))

    def test_main_passes_active_session_to_email_capability_preflight(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn("route_capability_preflight(effective,session_key)", source)

    def test_agentmail_approval_reruns_original_natural_request(self):
        source = Path("agentie/core/capability_preflight.py").read_text(encoding="utf-8")
        self.assertIn('approval["card"]["command"] = text', source)


if __name__ == "__main__":
    unittest.main()
