import unittest
from pathlib import Path


class AgentUIRegressionTests(unittest.TestCase):
    def test_loaded_plugins_script_is_the_single_agent_ui_source(self):
        text = Path("frontend/plugins.js").read_text(encoding="utf-8")
        self.assertIn("// Single persistent-agent UI implementation.", text)
        self.assertIn("__agentieAgentUIWired", text)
        self.assertIn("agent-role-tag", text)
        self.assertIn("agent-last-message", text)
        self.assertIn("agent_handoff", text)
        self.assertFalse(Path("frontend/agent_ui.js").exists())

    def test_agent_sidebar_has_role_tags_last_message_and_editing(self):
        text = Path("frontend/plugins.js").read_text(encoding="utf-8")
        self.assertIn("Agent name", text)
        self.assertIn("Role / title", text)
        self.assertIn("Rename agent", text)
        self.assertIn("Change agent", text)

    def test_one_overflow_menu_contains_all_three_agent_actions(self):
        text = Path("frontend/plugins.js").read_text(encoding="utf-8")
        enhancement = text.split("// Single persistent-agent UI implementation.", 1)[1]
        self.assertEqual(enhancement.count("Edit name & role"), 1)
        self.assertEqual(enhancement.count("View / edit instructions"), 1)
        self.assertEqual(enhancement.count("Delete agent"), 1)
        self.assertIn("menu.append(editItem,instructions,deleteItem)", enhancement)

    def test_delete_reuses_existing_approval_button(self):
        text = Path("frontend/plugins.js").read_text(encoding="utf-8")
        enhancement = text.split("// Single persistent-agent UI implementation.", 1)[1]
        self.assertIn(".agent-delete{display:none!important}", enhancement)
        self.assertIn("if(del)del.click()", enhancement)
        self.assertIn("querySelector('.agent-delete')", enhancement)
        self.assertNotIn("/approvals/", enhancement)

    def test_loaded_ui_preserves_plugins_mcp_and_web_snapshot(self):
        text = Path("frontend/plugins.js").read_text(encoding="utf-8")
        self.assertIn("agentiePluginsButton", text)
        self.assertIn("mcp_approval", text)
        self.assertIn("web_snapshot", text)
        self.assertIn("Always allow this tool", text)

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
        self.assertIn("(?:title|role|job)", roles)


if __name__ == "__main__":
    unittest.main()
