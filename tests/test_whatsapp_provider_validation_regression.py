import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agentie.core import plugin_connection_validation, plugin_credentials


class WhatsAppProviderValidationRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.temp.name)
        self.old_workspace = plugin_credentials.WORKSPACE
        self.old_credentials = plugin_credentials.CREDENTIALS_FILE
        plugin_credentials.WORKSPACE = root
        plugin_credentials.CREDENTIALS_FILE = root / "plugin_credentials.json"
        plugin_credentials.save_credentials("whatsapp", {
            "WHATSAPP_ACCESS_TOKEN": "provider-validation-token",
            "WHATSAPP_PHONE_NUMBER_ID": "123456789012345",
            "WHATSAPP_VERIFY_TOKEN": "verify-provider-test",
            "WHATSAPP_APP_SECRET": "app-provider-test",
        })

    def tearDown(self):
        plugin_credentials.WORKSPACE = self.old_workspace
        plugin_credentials.CREDENTIALS_FILE = self.old_credentials
        self.temp.cleanup()

    def test_validation_calls_meta_phone_number_resource_with_bearer_token(self):
        fake = MagicMock();fake.__enter__.return_value = fake
        fake.read.return_value = json.dumps({
            "id": "123456789012345",
            "display_phone_number": "+234 900 000 0000",
            "verified_name": "Agentie Test",
        }).encode("utf-8")
        with patch("agentie.core.plugin_connection_validation.urlopen", return_value=fake) as call:
            result = plugin_connection_validation.validate_plugin_connection("whatsapp")
        request = call.call_args.args[0]
        self.assertIn("graph.facebook.com/v23.0/123456789012345", request.full_url)
        self.assertIn("fields=id,display_phone_number,verified_name", request.full_url)
        self.assertEqual(request.get_header("Authorization"), "Bearer provider-validation-token")
        self.assertEqual(result["provider"], "Meta WhatsApp Cloud API")
        self.assertEqual(result["phone_number_id"], "123456789012345")

    def test_non_whatsapp_plugins_do_not_get_fake_provider_validation(self):
        with patch("agentie.core.plugin_connection_validation.urlopen") as call:
            self.assertIsNone(plugin_connection_validation.validate_plugin_connection("agentmail"))
        call.assert_not_called()

    def test_whatsapp_mcp_validates_meta_before_stdio_server_starts(self):
        source = Path("agentie/mcp_whatsapp_server.py").read_text(encoding="utf-8")
        validate = source.index('validate_plugin_connection("whatsapp")')
        run = source.index('mcp.run(transport="stdio")')
        self.assertLess(validate, run)

    def test_validation_module_never_places_token_in_return_value(self):
        fake = MagicMock();fake.__enter__.return_value = fake
        fake.read.return_value = b'{"id":"123456789012345","verified_name":"Agentie Test"}'
        with patch("agentie.core.plugin_connection_validation.urlopen", return_value=fake):
            result = plugin_connection_validation.validate_plugin_connection("whatsapp")
        self.assertNotIn("provider-validation-token", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
