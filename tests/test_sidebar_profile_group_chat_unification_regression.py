import unittest
from pathlib import Path


class SidebarProfileGroupChatUnificationRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("frontend/model_router.js").read_text(encoding="utf-8")

    def test_profile_is_inserted_below_plugins_and_menu_opens_upward(self):
        src = self.source
        for marker in (
            "agentie-profile-wrap",
            "agentie-profile-button",
            "agentiePluginsButton",
            "insertAdjacentElement('afterend',wrap)",
            "data-profile-action=\"settings\"",
            "data-profile-action=\"activity\"",
            "data-profile-action=\"automation\"",
            "bottom:calc(100% + 6px)",
        ):
            self.assertIn(marker, src)

    def test_ai_model_lives_in_settings_not_under_sidebar_search(self):
        src = self.source
        for marker in (
            "openSettings()",
            "data-model-slot",
            "__agentieMountModelRouter",
            "model-router-control",
            "/platform/model-routing/status",
            "/platform/model-routing/mode",
            "Local",
            "Auto",
            "Powerful",
        ):
            self.assertIn(marker, src)
        self.assertNotIn("search.after(control)", src)
        self.assertNotIn("const sidebar=document.querySelector('.sidebar'),search=", src)

    def test_at_palette_shows_agents_first_and_navigation_surfaces(self):
        src = self.source
        self.assertIn("agentie-at-menu", src)
        self.assertIn("function atToken", src)
        self.assertIn("heading('Agents')", src)
        agents_at = src.index("heading('Agents')")
        nav_at = src.index("heading('Navigate')")
        groups_at = src.index("heading('Group chats')")
        self.assertLess(agents_at, nav_at)
        self.assertLess(nav_at, groups_at)
        for marker in ("'Plugins'", "'Activity'", "'Agent chats'", "'Automation'"):
            self.assertIn(marker, src)

    def test_group_chats_are_sidebar_rows_with_overlapping_agent_heads(self):
        src = self.source
        for marker in (
            "sidebar-group-row",
            "group-avatar-stack",
            "group-avatar-head",
            "label.style.order='20000'",
            "row.style.order=String(order++)",
            "/platform/agent-chats",
            "window.__agentieOpenGroupChat=openGroupChat",
        ):
            self.assertIn(marker, src)

    def test_group_chat_reuses_normal_messages_and_composer(self):
        src = self.source
        for marker in (
            "document.getElementById('messages')",
            "document.getElementById('messageInput')",
            "#sendButton",
            "row.className=isUser?'user-row':'assistant-row'",
            "bubble.className='bubble '+(isUser?'user':'assistant')",
            "/platform/agent-chats/${encodeURIComponent(activeGroup.id)}/messages",
            "Message ${d.name}...",
        ):
            self.assertIn(marker, src)
        self.assertNotIn("openConnectedThread", src)

    def test_old_sidebar_chat_activity_automation_launchers_are_hidden(self):
        src = self.source
        self.assertIn("function hideOldLaunchers", src)
        self.assertIn("t.includes('agent chat')||t==='activity'||t==='automation'", src)
        self.assertIn("document.querySelector('.sidebar .model-router-control')?.remove()", src)


if __name__ == "__main__":
    unittest.main()
