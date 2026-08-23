import unittest
from pathlib import Path


class SidebarProfileGroupChatUnificationRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("frontend/navigation_connect.js").read_text(encoding="utf-8")
        cls.model_source = Path("frontend/model_router.js").read_text(encoding="utf-8")

    def test_profile_is_below_plugins_and_menu_opens_upward(self):
        src = self.source
        for marker in (
            "agentie-connected-profile",
            "agentie-connected-profile-button",
            "agentiePluginsButton",
            'data-connected-profile="settings"',
            'data-connected-profile="activity"',
            'data-connected-profile="automation"',
            "bottom:calc(100% + 6px)",
        ):
            self.assertIn(marker, src)

    def test_ai_model_lives_in_settings_and_model_router_has_no_chat_owner(self):
        nav = self.source
        model = self.model_source
        for marker in (
            "openSettings()",
            "data-model-slot",
            "__agentieMountModelRouter",
        ):
            self.assertIn(marker, nav)
        for marker in (
            "model-router-control",
            "/platform/model-routing/status",
            "/platform/model-routing/mode",
            "Local",
            "Auto",
            "Powerful",
        ):
            self.assertIn(marker, model)
        self.assertNotIn("/platform/agent-chats", model)
        self.assertNotIn("activeGroup", model)
        self.assertNotIn("sidebar-group-row", model)

    def test_at_palette_shows_agents_first_then_navigation_then_groups(self):
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
            "agentie-connected-sidebar-stack",
            "agentie-connected-sidebar-dot",
            "label.style.order='20000'",
            "row.style.order=String(order++)",
            "/platform/agent-chats",
            "window.__agentieOpenGroupChat=openGroup",
        ):
            self.assertIn(marker, src)

    def test_group_chat_reuses_normal_messages_and_composer(self):
        src = self.source
        for marker in (
            "document.getElementById('messages')",
            "document.getElementById('messageInput')",
            "document.getElementById('sendButton')",
            "row.className=isUser?'user-row':'assistant-row'",
            "bubble.className='bubble '+(isUser?'user':'assistant')",
            "/platform/agent-chats/${encodeURIComponent(id)}/messages",
            "Message ${d.name}...",
        ):
            self.assertIn(marker, src)
        self.assertNotIn("openConnectedThread", src)

    def test_old_sidebar_launchers_are_hidden_but_real_handlers_remain_reusable(self):
        src = self.source
        self.assertIn(".sidebar>.platform-activity-launch", src)
        self.assertIn(".sidebar>.n4-auto", src)
        self.assertIn(".sidebar>.n4-market", src)
        self.assertIn("function nativeLauncher", src)
        self.assertIn("function invokeNative", src)


if __name__ == "__main__":
    unittest.main()
