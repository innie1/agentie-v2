import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agentie.core import agent_access, browser_monitor, capability_preflight, capability_router, mcp_client, plugin_credentials
from agentie.core.mcp_catalog import preset_by_id


class GoogleCanvaMCPRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.old_registry = mcp_client.REGISTRY
        self.old_workspace = plugin_credentials.WORKSPACE
        self.old_credentials = plugin_credentials.CREDENTIALS_FILE
        self.old_client_id = os.environ.get("GOOGLE_CLIENT_ID")
        self.old_client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
        mcp_client.REGISTRY = root / "mcp_servers.json"
        plugin_credentials.WORKSPACE = root
        plugin_credentials.CREDENTIALS_FILE = root / "plugin_credentials.json"
        os.environ.pop("GOOGLE_CLIENT_ID", None)
        os.environ.pop("GOOGLE_CLIENT_SECRET", None)

    def tearDown(self):
        mcp_client.REGISTRY = self.old_registry
        plugin_credentials.WORKSPACE = self.old_workspace
        plugin_credentials.CREDENTIALS_FILE = self.old_credentials
        if self.old_client_id is None:
            os.environ.pop("GOOGLE_CLIENT_ID", None)
        else:
            os.environ["GOOGLE_CLIENT_ID"] = self.old_client_id
        if self.old_client_secret is None:
            os.environ.pop("GOOGLE_CLIENT_SECRET", None)
        else:
            os.environ["GOOGLE_CLIENT_SECRET"] = self.old_client_secret
        self.temp.cleanup()

    def test_google_workspace_preset_covers_core_google_suite(self):
        item = preset_by_id("google-workspace")
        self.assertIsNotNone(item)
        caps = set(item.get("capabilities") or [])
        self.assertTrue({"gmail", "drive", "docs", "sheets", "slides", "calendar", "contacts"}.issubset(caps))
        self.assertIn("@dguido/google-workspace-mcp", item.get("command", ""))
        setup = item.get("setup") or {}
        self.assertEqual(setup.get("auth_mode"), "oauth_with_credentials")
        fields = {x.get("env") for x in setup.get("fields") or []}
        self.assertEqual(fields, {"GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"})
        self.assertIn("auth", setup.get("oauth_command", ""))

    def test_google_defaults_and_credentials_are_isolated_to_google_server(self):
        plugin_credentials.save_credentials("google-workspace", {
            "GOOGLE_CLIENT_ID": "client.apps.googleusercontent.com",
            "GOOGLE_CLIENT_SECRET": "super-secret",
        })
        env = plugin_credentials.server_environment("google-workspace")
        self.assertEqual(env["GOOGLE_CLIENT_ID"], "client.apps.googleusercontent.com")
        self.assertEqual(env["GOOGLE_CLIENT_SECRET"], "super-secret")
        self.assertIn("gmail", env["GOOGLE_WORKSPACE_SERVICES"])
        self.assertIn("drive", env["GOOGLE_WORKSPACE_SERVICES"])
        self.assertEqual(env["GOOGLE_WORKSPACE_TOON_FORMAT"], "true")
        self.assertNotIn("GOOGLE_CLIENT_SECRET", plugin_credentials.server_environment("agentmail"))
        state = plugin_credentials.public_setup_state("google-workspace")
        self.assertTrue(state["configured"])
        self.assertTrue(state["oauth_supported"])
        self.assertNotIn("super-secret", json.dumps(state))

    def test_google_oauth_refuses_to_start_before_required_client_credentials(self):
        with self.assertRaises(ValueError):
            plugin_credentials.start_oauth_connection("google-workspace")

    def test_google_oauth_launches_curated_auth_with_secrets_only_in_environment(self):
        plugin_credentials.save_credentials("google-workspace", {
            "GOOGLE_CLIENT_ID": "client.apps.googleusercontent.com",
            "GOOGLE_CLIENT_SECRET": "super-secret",
        })
        fake = Mock(pid=4321)
        with patch("agentie.core.plugin_credentials.subprocess.Popen", return_value=fake) as popen:
            result = plugin_credentials.start_oauth_connection("google-workspace")
        self.assertTrue(result["started"])
        command = popen.call_args.args[0]
        kwargs = popen.call_args.kwargs
        self.assertIn("@dguido/google-workspace-mcp", command)
        self.assertIn("auth", command)
        self.assertNotIn("super-secret", command)
        self.assertEqual(kwargs["env"]["GOOGLE_CLIENT_SECRET"], "super-secret")

    def test_canva_preset_uses_official_mcp_and_browser_oauth(self):
        item = preset_by_id("canva")
        self.assertIsNotNone(item)
        self.assertIn("https://mcp.canva.com/mcp", item.get("command", ""))
        setup = item.get("setup") or {}
        self.assertEqual(setup.get("auth_mode"), "oauth")
        self.assertEqual(setup.get("fields") or [], [])
        self.assertIn("mcp-remote-client", setup.get("oauth_command", ""))
        self.assertIn("canva.dev", setup.get("docs_url", ""))

    def test_canva_oauth_can_start_without_pasted_secret(self):
        fake = Mock(pid=2468)
        with patch("agentie.core.plugin_credentials.subprocess.Popen", return_value=fake) as popen:
            result = plugin_credentials.start_oauth_connection("canva")
        self.assertTrue(result["started"])
        self.assertIn("mcp-remote-client", popen.call_args.args[0])
        self.assertNotIn("CANVA_API_KEY", popen.call_args.kwargs["env"])

    def test_explicit_gmail_is_not_claimed_by_agentmail_preflight(self):
        self.assertFalse(capability_preflight._agentmail_intent("Check my Gmail"))
        self.assertTrue(capability_preflight._agentmail_intent("Check my email"))

    def test_natural_permission_routing_separates_google_canva_and_agentmail(self):
        servers = [{"name": "agentmail"}, {"name": "google-workspace"}, {"name": "canva"}]
        with patch.object(agent_access, "list_servers", return_value=servers):
            self.assertEqual(agent_access._mentioned_mcp("Check my Gmail"), "google-workspace")
            self.assertEqual(agent_access._mentioned_mcp("Search Google Drive for budget"), "google-workspace")
            self.assertEqual(agent_access._mentioned_mcp("Search Canva designs for laundry"), "canva")
            self.assertEqual(agent_access._mentioned_mcp("Check my email"), "agentmail")

    def test_check_gmail_maps_to_google_search_emails(self):
        info = {"tools": [{"name": "searchEmails", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "maxResults": {"type": "number"}}}}]}
        choice = capability_router._google_workspace_choice("Check my Gmail", {"name": "google-workspace"}, info)
        self.assertIsNotNone(choice)
        self.assertEqual(choice[0], "searchEmails")
        self.assertEqual(choice[1]["query"], "in:inbox")

    def test_send_gmail_maps_to_send_email_with_real_recipient_fields(self):
        info = {"tools": [{"name": "sendEmail", "input_schema": {"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}}, "required": ["to", "subject", "body"]}}]}
        choice = capability_router._google_workspace_choice(
            "Send Gmail to test@example.com subject Hello saying This is a test",
            {"name": "google-workspace"},
            info,
        )
        self.assertEqual(choice[0], "sendEmail")
        self.assertEqual(choice[1]["to"], "test@example.com")
        self.assertEqual(choice[1]["subject"], "Hello")
        self.assertEqual(choice[1]["body"], "This is a test")

    def test_google_drive_search_maps_to_drive_search_tool(self):
        info = {"tools": [{"name": "search", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}]}
        choice = capability_router._google_workspace_choice("Search Google Drive for budget 2026", {"name": "google-workspace"}, info)
        self.assertEqual(choice[0], "search")
        self.assertEqual(choice[1]["query"], "budget 2026")

    def test_canva_search_uses_discovered_canva_tool(self):
        info = {"tools": [{"name": "search-designs", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}}}]}
        choice = capability_router._canva_choice("Search Canva designs for laundry", {"name": "canva"}, info)
        self.assertEqual(choice[0], "search-designs")
        self.assertEqual(choice[1]["query"], "laundry")

    def test_google_workspace_registration_suppresses_gmail_computer_fallback(self):
        with patch.object(browser_monitor, "_connected_plugin_names", return_value={"google-workspace"}):
            self.assertIsNone(browser_monitor._service_for_task("Check my Gmail"))
            self.assertIsNone(browser_monitor._service_for_task("Check my Google Calendar"))

    def test_direct_capability_routing_runs_before_manager_auto_delegation(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertLess(source.index("direct_capability=await route_capability_request"), source.index("handoff=maybe_auto_delegate"))


if __name__ == "__main__":
    unittest.main()
