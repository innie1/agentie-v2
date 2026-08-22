import asyncio
import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agentie.core import agent_access, agent_registry, mcp_client, plugin_credentials, whatsapp_cloud, whatsapp_preflight
from agentie.core.mcp_catalog import preset_by_id


class WhatsAppCloudRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.temp.name)
        self.old_agents = agent_registry.AGENTS_FILE
        self.old_registry = mcp_client.REGISTRY
        self.old_credentials = plugin_credentials.CREDENTIALS_FILE
        self.old_plugin_workspace = plugin_credentials.WORKSPACE
        self.old_history = whatsapp_cloud.HISTORY_FILE
        self.old_settings = whatsapp_cloud.SETTINGS_FILE
        self.old_events = whatsapp_cloud.EVENTS_FILE
        self.old_access = agent_access.GLOBAL_ACCESS_FILE
        agent_registry.AGENTS_FILE = root / "agents.json"
        mcp_client.REGISTRY = root / "mcp_servers.json"
        plugin_credentials.WORKSPACE = root
        plugin_credentials.CREDENTIALS_FILE = root / "plugin_credentials.json"
        whatsapp_cloud.HISTORY_FILE = root / "whatsapp_history.json"
        whatsapp_cloud.SETTINGS_FILE = root / "whatsapp_settings.json"
        whatsapp_cloud.EVENTS_FILE = root / "whatsapp_events.json"
        agent_access.GLOBAL_ACCESS_FILE = root / "capability_access.json"
        self.ben = agent_registry.create_agent("Ben", "Sales & Outreach", "general")["agent"]
        self.support = agent_registry.create_agent("Nora", "Customer Support", "general")["agent"]

    def tearDown(self):
        agent_registry.AGENTS_FILE = self.old_agents
        mcp_client.REGISTRY = self.old_registry
        plugin_credentials.CREDENTIALS_FILE = self.old_credentials
        plugin_credentials.WORKSPACE = self.old_plugin_workspace
        whatsapp_cloud.HISTORY_FILE = self.old_history
        whatsapp_cloud.SETTINGS_FILE = self.old_settings
        whatsapp_cloud.EVENTS_FILE = self.old_events
        agent_access.GLOBAL_ACCESS_FILE = self.old_access
        self.temp.cleanup()

    def _save_meta_credentials(self):
        plugin_credentials.save_credentials("whatsapp", {
            "WHATSAPP_ACCESS_TOKEN": "test-meta-access-token-9f2d",
            "WHATSAPP_PHONE_NUMBER_ID": "123456789012345",
            "WHATSAPP_VERIFY_TOKEN": "test-webhook-verify-token-7ac4",
            "WHATSAPP_APP_SECRET": "test-meta-app-secret-5e91",
        })

    def _webhook_payload(self, body="Hello", message_id="wamid.in.1", phone="2348012345678"):
        return {
            "entry": [{
                "changes": [{
                    "field": "messages",
                    "value": {
                        "metadata": {"display_phone_number": "+2349000000000", "phone_number_id": "123456789012345"},
                        "contacts": [{"wa_id": phone, "profile": {"name": "John Customer"}}],
                        "messages": [{
                            "from": phone,
                            "id": message_id,
                            "timestamp": "1700000000",
                            "type": "text",
                            "text": {"body": body},
                        }],
                    },
                }],
            }],
        }

    def test_catalog_has_real_whatsapp_cloud_preset_and_setup(self):
        item = preset_by_id("whatsapp")
        self.assertIsNotNone(item)
        self.assertIn("agentie.mcp_whatsapp_server", item.get("command", ""))
        self.assertIn("whatsapp", set(item.get("capabilities") or []))
        self.assertIn("send_whatsapp_text", set(item.get("sensitive_tools") or []))
        setup = item.get("setup") or {}
        fields = {x.get("env") for x in setup.get("fields") or []}
        self.assertEqual(fields, {
            "WHATSAPP_ACCESS_TOKEN",
            "WHATSAPP_PHONE_NUMBER_ID",
            "WHATSAPP_VERIFY_TOKEN",
            "WHATSAPP_APP_SECRET",
        })
        self.assertEqual(setup.get("webhook_path"), "/webhooks/whatsapp")
        self.assertIn("developers.facebook.com", setup.get("docs_url", ""))

    def test_setup_state_requires_all_meta_fields_and_never_returns_secret_values(self):
        plugin_credentials.save_credentials("whatsapp", {"WHATSAPP_ACCESS_TOKEN": "private-token-only"})
        state = plugin_credentials.public_setup_state("whatsapp")
        self.assertFalse(state["configured"])
        self.assertTrue(state["requires_credentials"])
        self.assertEqual(state["webhook_path"], "/webhooks/whatsapp")
        self.assertNotIn("private-token-only", json.dumps(state))
        self.assertTrue(all(item.get("help") for item in state["fields"]))
        self._save_meta_credentials()
        state = plugin_credentials.public_setup_state("whatsapp")
        self.assertTrue(state["configured"])
        public_text = json.dumps(state)
        self.assertNotIn("test-meta-access-token-9f2d", public_text)
        self.assertNotIn("test-meta-app-secret-5e91", public_text)

    def test_phone_normalization_uses_international_digits(self):
        self.assertEqual(whatsapp_cloud.normalize_phone("+234 801 234 5678"), "2348012345678")
        with self.assertRaises(ValueError):
            whatsapp_cloud.normalize_phone("1234")

    def test_send_text_uses_official_graph_messages_endpoint_and_bearer_token(self):
        self._save_meta_credentials()
        fake = MagicMock()
        fake.__enter__.return_value = fake
        fake.read.return_value = b'{"messages":[{"id":"wamid.out.1"}]}'
        with patch("agentie.core.whatsapp_cloud.urlopen", return_value=fake) as call:
            result = whatsapp_cloud.send_text_message("+2348012345678", "Hello", agent=self.ben)
        request = call.call_args.args[0]
        self.assertIn("graph.facebook.com/v23.0/123456789012345/messages", request.full_url)
        self.assertEqual(request.get_header("Authorization"), "Bearer test-meta-access-token-9f2d")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["messaging_product"], "whatsapp")
        self.assertEqual(payload["to"], "2348012345678")
        self.assertEqual(payload["type"], "text")
        self.assertIn("Ben", payload["text"]["body"])
        self.assertIn("AI Sales & Outreach Agent", payload["text"]["body"])
        self.assertEqual(result["message"]["agent_name"], "Ben")
        self.assertEqual(result["message"]["agent_role"], "Sales & Outreach")

    def test_template_send_uses_real_template_payload(self):
        self._save_meta_credentials()
        fake = MagicMock();fake.__enter__.return_value = fake;fake.read.return_value = b'{"messages":[{"id":"wamid.tpl.1"}]}'
        with patch("agentie.core.whatsapp_cloud.urlopen", return_value=fake) as call:
            whatsapp_cloud.send_template_message("2348012345678", "order_ready", "en_US", agent=self.ben)
        payload = json.loads(call.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(payload["type"], "template")
        self.assertEqual(payload["template"]["name"], "order_ready")
        self.assertEqual(payload["template"]["language"]["code"], "en_US")

    def test_webhook_challenge_requires_matching_verify_token(self):
        self._save_meta_credentials()
        self.assertEqual(whatsapp_cloud.verify_webhook_challenge("subscribe", "test-webhook-verify-token-7ac4", "9876"), "9876")
        self.assertIsNone(whatsapp_cloud.verify_webhook_challenge("subscribe", "wrong", "9876"))

    def test_webhook_signature_requires_valid_hmac_sha256(self):
        self._save_meta_credentials()
        body = b'{"object":"whatsapp_business_account"}'
        digest = hmac.new(b"test-meta-app-secret-5e91", body, hashlib.sha256).hexdigest()
        self.assertTrue(whatsapp_cloud.verify_webhook_signature(body, f"sha256={digest}"))
        self.assertFalse(whatsapp_cloud.verify_webhook_signature(body, "sha256=bad"))
        self.assertFalse(whatsapp_cloud.verify_webhook_signature(body, None))

    def test_incoming_webhook_routes_to_support_agent_and_deduplicates(self):
        whatsapp_cloud.set_support_agent("Nora")
        result = whatsapp_cloud.ingest_webhook(self._webhook_payload())
        self.assertEqual(result["received"], 1)
        item = whatsapp_cloud.get_message("wamid.in.1")
        self.assertEqual(item["routed_agent_name"], "Nora")
        self.assertEqual(item["profile_name"], "John Customer")
        second = whatsapp_cloud.ingest_webhook(self._webhook_payload())
        self.assertEqual(second["duplicates"], 1)
        self.assertEqual(len(whatsapp_cloud.list_messages()), 1)

    def test_explicit_contact_assignment_overrides_support_agent(self):
        whatsapp_cloud.set_support_agent("Nora")
        whatsapp_cloud.assign_contact("+2348012345678", "Ben")
        routed = whatsapp_cloud.route_incoming_agent("2348012345678", "Need a quote")
        self.assertEqual(routed["name"], "Ben")

    def test_disabling_support_mode_stops_automatic_routing_but_preserves_contact_assignment(self):
        whatsapp_cloud.set_support_agent("Nora")
        whatsapp_cloud.set_support_mode(False)
        self.assertIsNone(whatsapp_cloud.route_incoming_agent("2348022222222", "Hello"))
        whatsapp_cloud.assign_contact("2348012345678", "Ben")
        self.assertEqual(whatsapp_cloud.route_incoming_agent("2348012345678", "Hello")["name"], "Ben")

    def test_human_escalation_detects_customer_request_and_sensitive_disputes(self):
        self.assertEqual(whatsapp_cloud.escalation_reason("Please let me speak to a human"), "Customer requested a human")
        self.assertEqual(whatsapp_cloud.escalation_reason("I want a refund for this charge"), "Payment/refund dispute")
        self.assertEqual(whatsapp_cloud.escalation_reason("My lawyer will contact you"), "Legal or regulatory issue")
        self.assertIsNone(whatsapp_cloud.escalation_reason("What time do you close?"))

    def test_escalated_webhook_is_flagged_for_human_attention(self):
        whatsapp_cloud.set_support_agent("Nora")
        whatsapp_cloud.ingest_webhook(self._webhook_payload("I need a refund and a human", "wamid.human.1"))
        item = whatsapp_cloud.get_message("wamid.human.1")
        self.assertTrue(item["needs_human"])
        self.assertIn("human", item["escalation_reason"].lower())
        human = whatsapp_cloud.list_messages(needs_human=True)
        self.assertEqual(human[0]["id"], "wamid.human.1")

    def test_incoming_event_is_delivered_once_to_agentie_polling(self):
        whatsapp_cloud.set_support_agent("Nora")
        whatsapp_cloud.ingest_webhook(self._webhook_payload())
        first = whatsapp_cloud.poll_events()
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["card"]["title"], "WhatsApp · Incoming")
        self.assertIn("Nora", first[0]["card"]["content"])
        self.assertEqual(whatsapp_cloud.poll_events(), [])

    def test_mcp_server_exposes_real_whatsapp_tools_and_sender_identity_fields(self):
        source = Path("agentie/mcp_whatsapp_server.py").read_text(encoding="utf-8")
        self.assertIn('FastMCP("Agentie WhatsApp Cloud")', source)
        for name in ("list_whatsapp_messages", "get_whatsapp_message", "send_whatsapp_text", "send_whatsapp_template", "mark_whatsapp_read"):
            self.assertIn(f"def {name}", source)
        self.assertIn("agent_name: str", source)
        self.assertIn("company_identity: str", source)
        self.assertIn('mcp.run(transport="stdio")', source)

    def test_check_whatsapp_surfaces_setup_card_when_required_meta_credentials_are_missing(self):
        with patch("agentie.core.whatsapp_preflight.list_servers", return_value=[{"name":"whatsapp"}]):
            result = asyncio.run(whatsapp_preflight.route_whatsapp("Check WhatsApp", f"{self.ben['session_prefix']}main"))
        self.assertEqual(result["card"]["type"], "mcp_setup")
        self.assertEqual(result["card"]["server"], "whatsapp")
        self.assertEqual(result["card"]["retry_command"], "Check WhatsApp")

    def test_natural_send_requires_existing_mcp_approval_before_execution_and_carries_agent_identity(self):
        self._save_meta_credentials()
        info = {"tools":[{"name":"send_whatsapp_text"}]}
        captured = {}
        def fake_approval(server, tool, arguments, command, natural=False):
            captured.update(arguments)
            return {"approved":False,"card":{"type":"mcp_approval","server":server,"tool":tool,"arguments":arguments,"command":command}}
        with patch("agentie.core.whatsapp_preflight.list_servers", return_value=[{"name":"whatsapp"}]), \
             patch("agentie.core.whatsapp_preflight.inspect_server", return_value=info), \
             patch("agentie.core.whatsapp_preflight._approval_response", side_effect=fake_approval), \
             patch("agentie.core.whatsapp_preflight.execute_tool") as execute:
            result = asyncio.run(whatsapp_preflight.route_whatsapp("Send WhatsApp to +2348012345678 saying Hello John", f"{self.ben['session_prefix']}main"))
        self.assertEqual(result["card"]["type"], "mcp_approval")
        execute.assert_not_called()
        self.assertEqual(captured["agent_name"], "Ben")
        self.assertEqual(captured["agent_role"], "Sales & Outreach")
        self.assertIn("Ben", captured["text"])
        self.assertIn("AI Sales & Outreach Agent", captured["text"])

    def test_mark_read_also_uses_approval_instead_of_silent_external_mutation(self):
        self._save_meta_credentials();info={"tools":[{"name":"mark_whatsapp_read"}]}
        with patch("agentie.core.whatsapp_preflight.list_servers", return_value=[{"name":"whatsapp"}]), \
             patch("agentie.core.whatsapp_preflight.inspect_server", return_value=info), \
             patch("agentie.core.whatsapp_preflight._approval_response", return_value={"approved":False,"card":{"type":"mcp_approval"}}), \
             patch("agentie.core.whatsapp_preflight.execute_tool") as execute:
            result = asyncio.run(whatsapp_preflight.route_whatsapp("Mark WhatsApp message wamid.test.123 as read", f"{self.ben['session_prefix']}main"))
        self.assertEqual(result["card"]["type"], "mcp_approval")
        execute.assert_not_called()

    def test_agent_capability_guard_recognizes_natural_whatsapp_requests(self):
        with patch.object(agent_access, "list_servers", return_value=[{"name":"whatsapp"}]):
            self.assertEqual(agent_access._mentioned_mcp("Send WhatsApp to +2348012345678 saying hello"), "whatsapp")
            self.assertEqual(agent_access._mentioned_mcp("Check WhatsApp messages"), "whatsapp")

    def test_main_wires_secure_whatsapp_webhook_and_event_poll(self):
        source = Path("main.py").read_text(encoding="utf-8")
        webhook = Path("agentie/core/whatsapp_webhook.py").read_text(encoding="utf-8")
        self.assertIn("app.include_router(whatsapp_router)", source)
        self.assertIn("poll_whatsapp_events()", source)
        self.assertIn('@router.get("/webhooks/whatsapp")', webhook)
        self.assertIn('@router.post("/webhooks/whatsapp")', webhook)
        self.assertIn("x-hub-signature-256", webhook)
        self.assertIn("verify_webhook_signature", webhook)

    def test_plugin_setup_ui_guides_webhook_setup_and_keeps_clear_confirmation(self):
        source = Path("frontend/plugin_setup.js").read_text(encoding="utf-8")
        self.assertIn("webhookMarkup", source)
        self.assertIn("Copy callback URL", source)
        self.assertIn("data-webhook-url", source)
        self.assertIn("f.help", source)
        self.assertIn("Clear saved secret?", source)
        self.assertIn("confirmClearSetup", source)

    def test_main_does_not_report_plugin_connected_when_required_fields_are_missing(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn('state.get("requires_credentials") and not state.get("configured")', source)
        self.assertIn("required setup fields", source)


if __name__ == "__main__":
    unittest.main()
