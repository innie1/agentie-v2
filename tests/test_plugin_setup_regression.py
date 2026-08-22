import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import mcp_client, plugin_credentials
from agentie.core.mcp_catalog import preset_by_id


class PluginSetupRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.old_registry = mcp_client.REGISTRY
        self.old_workspace = plugin_credentials.WORKSPACE
        self.old_credentials = plugin_credentials.CREDENTIALS_FILE
        self.old_agentmail = os.environ.get("AGENTMAIL_API_KEY")
        mcp_client.REGISTRY = root / "mcp_servers.json"
        plugin_credentials.WORKSPACE = root
        plugin_credentials.CREDENTIALS_FILE = root / "plugin_credentials.json"
        mcp_client.add_local_server("agentmail", "npx -y agentmail-mcp")

    def tearDown(self):
        mcp_client.REGISTRY = self.old_registry
        plugin_credentials.WORKSPACE = self.old_workspace
        plugin_credentials.CREDENTIALS_FILE = self.old_credentials
        if self.old_agentmail is None:
            os.environ.pop("AGENTMAIL_API_KEY", None)
        else:
            os.environ["AGENTMAIL_API_KEY"] = self.old_agentmail
        self.temp.cleanup()

    def test_agentmail_catalog_has_real_setup_metadata(self):
        item = preset_by_id("agentmail")
        self.assertIsNotNone(item)
        setup = item.get("setup") or {}
        field = (setup.get("fields") or [])[0]
        self.assertEqual(field.get("env"), "AGENTMAIL_API_KEY")
        self.assertIn("agentmail", setup.get("get_key_url", "").lower())
        self.assertIn("agentmail", setup.get("docs_url", "").lower())

    def test_secret_is_saved_but_never_returned_by_public_setup_state(self):
        secret = "am_super_secret_value"
        plugin_credentials.save_credentials("agentmail", {"AGENTMAIL_API_KEY": secret})
        raw = plugin_credentials.CREDENTIALS_FILE.read_text(encoding="utf-8")
        self.assertIn(secret, raw)
        state = plugin_credentials.public_setup_state("agentmail")
        self.assertTrue(state["configured"])
        self.assertTrue(state["fields"][0]["configured"])
        self.assertNotIn(secret, json.dumps(state))

    def test_stdio_mcp_receives_only_its_server_scoped_credentials(self):
        plugin_credentials.save_credentials("agentmail", {"AGENTMAIL_API_KEY": "am_test"})
        params = mcp_client._stdio_params(mcp_client.get_server("agentmail"))
        self.assertEqual(params.env.get("AGENTMAIL_API_KEY"), "am_test")
        plugin_credentials.save_credentials("other", {"OTHER_SECRET": "hidden"})
        params = mcp_client._stdio_params(mcp_client.get_server("agentmail"))
        self.assertNotIn("OTHER_SECRET", params.env)

    def test_connection_closed_becomes_inline_setup_card_with_retry(self):
        original = {"message": "AgentMail is registered but not connected: Connection closed.", "card": None}
        result = plugin_credentials.enrich_setup_failure("List my AgentMail inboxes", original)
        self.assertEqual(result["card"]["type"], "mcp_setup")
        self.assertEqual(result["card"]["server"], "agentmail")
        self.assertEqual(result["card"]["retry_command"], "List my AgentMail inboxes")
        self.assertIn("AGENTMAIL_API_KEY", json.dumps(result["card"]))

    def test_unrelated_failure_does_not_force_setup_card(self):
        original = {"message": "The requested message was not found.", "card": None}
        self.assertIs(plugin_credentials.enrich_setup_failure("Read message abc", original), original)

    def test_custom_mcp_credentials_are_supported_without_fake_metadata(self):
        mcp_client.add_local_server("custom-service", "npx -y some-mcp-package")
        plugin_credentials.save_credentials("custom-service", {"CUSTOM_SERVICE_TOKEN": "secret"})
        state = plugin_credentials.public_setup_state("custom-service")
        self.assertTrue(state["custom_env_supported"])
        self.assertEqual(state["fields"], [])
        self.assertEqual(plugin_credentials.server_environment("custom-service")["CUSTOM_SERVICE_TOKEN"], "secret")

    def test_invalid_environment_variable_is_rejected(self):
        with self.assertRaises(ValueError):
            plugin_credentials.save_credentials("agentmail", {"BAD KEY NAME": "secret"})

    def test_main_wires_both_inline_recovery_and_plugin_setup_endpoints(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn('/plugins/setup/{server_name}', source)
        self.assertIn('enrich_setup_failure(request.message,mcp)', source)
        self.assertIn('enrich_setup_failure(effective,preflight)', source)
        self.assertIn('/plugin-setup.js', source)
        self.assertIn('apply_all_credentials()', source)

    def test_frontend_supports_inline_card_and_plugins_page_configure(self):
        source = Path("frontend/plugin_setup.js").read_text(encoding="utf-8")
        self.assertIn("card.type==='mcp_setup'", source)
        self.assertIn("data-setup-mcp", source)
        self.assertIn("Save & test", source)
        self.assertIn("Get API key", source)
        self.assertIn("Configure", source)
        self.assertIn("type=\"password\"", source)


if __name__ == "__main__":
    unittest.main()
