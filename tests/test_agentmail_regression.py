import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agentie.core import capability_preflight
from agentie.core.mcp_catalog import preset_by_id


INFO = {
    "tools": [
        {"name": "list_inboxes"},
        {"name": "list_messages"},
        {"name": "search_messages"},
        {"name": "send_message"},
    ]
}
SERVER = {"name": "agentmail", "transport": "stdio", "command": "npx", "args": ["-y", "agentmail-mcp"]}


class AgentMailRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        self.patch = patch.object(capability_preflight, "WORKSPACE", self.workspace)
        self.patch.start()

    async def asyncTearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    async def test_agentmail_preset_exists(self):
        item = preset_by_id("agentmail")
        self.assertIsNotNone(item)
        self.assertIn("agentmail-mcp", item["command"])

    async def test_notification_email_is_saved_locally(self):
        result = await capability_preflight.route_capability_preflight("Set my notification email to me@example.com")
        self.assertIn("Saved", result["message"])
        self.assertEqual(capability_preflight._load_agentmail_settings()["notification_email"], "me@example.com")

    async def test_email_me_routes_to_agentmail_send_message(self):
        capability_preflight._save_agentmail_settings({"notification_email": "me@example.com", "inbox_id": "inbox_123"})
        with patch.object(capability_preflight, "_agentmail_server", return_value=SERVER), \
             patch.object(capability_preflight, "inspect_server", new=AsyncMock(return_value=INFO)), \
             patch.object(capability_preflight, "_approval_response", return_value={"approved": False, "card": {"type": "mcp_approval"}}) as approval:
            result = await capability_preflight.route_capability_preflight("Email me saying the build is complete")
        self.assertEqual(result["card"]["type"], "mcp_approval")
        args = approval.call_args.args
        self.assertEqual(args[0], "agentmail")
        self.assertEqual(args[1], "send_message")
        self.assertEqual(args[2]["inboxId"], "inbox_123")
        self.assertEqual(args[2]["to"], ["me@example.com"])
        self.assertIn("build is complete", args[2]["text"])

    async def test_email_without_sender_inbox_explains_setup(self):
        capability_preflight._save_agentmail_settings({"notification_email": "me@example.com"})
        with patch.object(capability_preflight, "_agentmail_server", return_value=SERVER), \
             patch.object(capability_preflight, "inspect_server", new=AsyncMock(return_value=INFO)):
            result = await capability_preflight.route_capability_preflight("Email me saying hello")
        self.assertIn("inbox", result["message"].lower())


if __name__ == "__main__":
    unittest.main()
