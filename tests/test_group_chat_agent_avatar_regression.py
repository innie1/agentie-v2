import unittest
from pathlib import Path


class GroupChatAgentAvatarRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("frontend/group_chat_instant_open.js").read_text(encoding="utf-8")

    def test_group_replies_use_agent_specific_colored_orbs(self):
        src = self.source
        for marker in (
            "__agentieGroupAvatarColorGuard",
            "agentie-connected-group-message-orb",
            "agentie-connected-group-agent-row",
            "resolveAgent(name)",
            "window.__agentieAgents",
            "orb.dataset.agentId",
            "orb.style.background=colorFor(agent?.id||name)",
            "orb.textContent=initials(agent?.name||name)",
            "row.prepend(orb)",
        ):
            self.assertIn(marker, src)

    def test_generic_group_assistant_pseudo_avatar_is_suppressed(self):
        src = self.source
        self.assertIn(".assistant-row.agentie-connected-group-agent-row::before", src)
        self.assertIn("display:none!important", src)
        self.assertIn("content:none!important", src)

    def test_avatar_layer_is_presentation_only_not_an_extra_chat_runtime(self):
        src = self.source
        self.assertNotIn("/platform/agent-chats", src)
        self.assertNotIn("setInterval(refreshGroup", src)
        self.assertNotIn("fetch(", src)


if __name__ == "__main__":
    unittest.main()
