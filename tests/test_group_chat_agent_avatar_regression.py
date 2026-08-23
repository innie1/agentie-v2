import unittest
from pathlib import Path


class GroupChatAgentAvatarRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = Path("frontend/navigation_connect.js").read_text(encoding="utf-8")
        cls.guard = Path("frontend/group_chat_instant_open.js").read_text(encoding="utf-8")

    def test_group_runtime_renders_agent_specific_colored_orbs_directly(self):
        src = self.runtime
        for marker in (
            "agentie-connected-group-message-orb",
            "agentie-connected-group-agent-row",
            "function messageOrb(message)",
            "message?.sender_id",
            "orb.dataset.agentId",
            "orb.style.background=colorFor(id)",
            "orb.textContent=initials(name)",
            "row.appendChild(messageOrb(m))",
        ):
            self.assertIn(marker, src)

    def test_generic_group_assistant_pseudo_avatar_is_suppressed_by_runtime(self):
        src = self.runtime
        self.assertIn(".assistant-row.agentie-connected-group-agent-row::before", src)
        self.assertIn("display:none!important", src)
        self.assertIn("content:none!important", src)

    def test_instant_open_guard_no_longer_owns_avatar_rendering(self):
        src = self.guard
        for marker in (
            "__agentieGroupAvatarColorGuard",
            "agentie-connected-group-message-orb",
            "resolveAgent(name)",
            "window.__agentieAgents",
        ):
            self.assertNotIn(marker, src)
        self.assertNotIn("/platform/agent-chats", src)
        self.assertNotIn("fetch(", src)

    def test_group_runtime_and_open_guard_share_one_scroll_root_contract(self):
        runtime = self.runtime
        guard = self.guard
        for marker in (
            "function scrollHost(){const shell=document.querySelector('.chat-shell')",
            "getComputedStyle(shell)",
            "if(/auto|scroll|overlay/.test(overflow))return shell",
            "document.scrollingElement||document.documentElement||document.body",
            "window.__agentieGroupScrollRoot=scrollHost",
        ):
            self.assertIn(marker, runtime)
        self.assertIn("window.__agentieGroupScrollRoot?.()", guard)
        self.assertIn("if(/auto|scroll|overlay/.test(overflow))return shell", guard)


if __name__ == "__main__":
    unittest.main()
