import unittest
from pathlib import Path


class AgentUIRegressionTests(unittest.TestCase):
    def test_agent_ui_source_is_additive(self):
        text = Path("frontend/agent_ui.js").read_text(encoding="utf-8")
        self.assertIn("const previous=window.renderCard", text)
        self.assertIn("return previous(c,m)", text)
        self.assertIn("agent_handoff", text)

    def test_loaded_plugins_script_wires_agent_ui(self):
        text = Path("frontend/plugins.js").read_text(encoding="utf-8")
        self.assertIn("__agentieAgentUIWired", text)
        self.assertIn("agent-role-tag", text)
        self.assertIn("agent-last-message", text)
        self.assertIn("agent_handoff", text)
        self.assertIn("agentie_agent_last_messages", text)

    def test_agent_sidebar_has_role_tags_last_message_and_editing(self):
        text = Path("frontend/plugins.js").read_text(encoding="utf-8")
        self.assertIn("Agent name", text)
        self.assertIn("Role / title", text)
        self.assertIn("Rename agent", text)
        self.assertIn("Change agent", text)
        self.assertIn("location.reload()", text)

    def test_loaded_ui_preserves_plugins_mcp_and_web_snapshot(self):
        text = Path("frontend/plugins.js").read_text(encoding="utf-8")
        self.assertIn("agentiePluginsButton", text)
        self.assertIn("mcp_approval", text)
        self.assertIn("web_snapshot", text)
        self.assertIn("Always allow this tool", text)

    def test_agent_ui_reuses_existing_delete_and_approval_flows(self):
        text = Path("frontend/plugins.js").read_text(encoding="utf-8")
        enhancement = text.split("// Persistent agent UI enhancement.", 1)[1]
        self.assertIn("querySelector('.agent-delete')", enhancement)
        self.assertNotIn("Delete agent ${", enhancement)
        self.assertNotIn("/approvals/", enhancement)
        self.assertNotIn("browser_approval", enhancement)

    def test_existing_desktop_and_browser_ui_files_remain_present(self):
        self.assertTrue(Path("frontend/browser_screen.js").exists())
        browser = Path("frontend/browser_screen.js").read_text(encoding="utf-8")
        self.assertIn("desktop_view", browser)
        self.assertIn("browser_approval", browser)
        self.assertIn("KasmVNC", browser)

    def test_backend_agent_profile_editing_remains_available(self):
        registry = Path("agentie/core/agent_registry.py").read_text(encoding="utf-8")
        roles = Path("agentie/core/role_store.py").read_text(encoding="utf-8")
        self.assertIn("def update_agent_profile", registry)
        self.assertIn("update_agent_profile(rename.group(1)", roles)
        self.assertIn("update_agent_profile(role_edit.group(1)", roles)
        self.assertIn("(?:title|role)", roles)


if __name__ == "__main__":
    unittest.main()
