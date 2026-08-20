import unittest
from pathlib import Path


class AgentUIRegressionTests(unittest.TestCase):
    def test_agent_ui_is_additive_and_preserves_existing_renderers(self):
        text = Path("frontend/agent_ui.js").read_text(encoding="utf-8")
        self.assertIn("const previous=window.renderCard", text)
        self.assertIn("return previous(c,m)", text)
        self.assertIn("agent_handoff", text)

    def test_agent_sidebar_has_role_tags_last_message_and_editing(self):
        text = Path("frontend/agent_ui.js").read_text(encoding="utf-8")
        self.assertIn("agent-role-tag", text)
        self.assertIn("agent-last-message", text)
        self.assertIn("Agent name", text)
        self.assertIn("Role / title", text)
        self.assertIn("Rename agent", text)
        self.assertIn("Change agent", text)

    def test_agent_ui_reuses_existing_delete_and_approval_flows(self):
        text = Path("frontend/agent_ui.js").read_text(encoding="utf-8")
        self.assertIn("querySelector('.agent-delete')", text)
        self.assertNotIn("Delete agent ${", text)
        self.assertNotIn("/approvals/", text)
        self.assertNotIn("browser_approval", text)

    def test_existing_desktop_and_browser_ui_files_remain_present(self):
        self.assertTrue(Path("frontend/browser_screen.js").exists())
        browser = Path("frontend/browser_screen.js").read_text(encoding="utf-8")
        self.assertIn("desktop_view", browser)
        self.assertIn("browser_approval", browser)

    def test_backend_agent_profile_editing_remains_available(self):
        registry = Path("agentie/core/agent_registry.py").read_text(encoding="utf-8")
        roles = Path("agentie/core/role_store.py").read_text(encoding="utf-8")
        self.assertIn("def update_agent_profile", registry)
        self.assertIn("update_agent_profile(rename.group(1)", roles)
        self.assertIn("update_agent_profile(role_edit.group(1)", roles)
        self.assertIn("(?:title|role)", roles)


if __name__ == "__main__":
    unittest.main()
