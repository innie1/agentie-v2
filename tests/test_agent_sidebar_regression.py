import unittest
from pathlib import Path


class AgentSidebarRegressionTests(unittest.TestCase):
    def test_sidebar_renders_persistent_agent_orbs(self):
        text=Path("frontend/index.html").read_text(encoding="utf-8")
        self.assertIn('id="persistentAgentList"',text)
        self.assertIn("orb.className='agent-orb'",text)
        self.assertIn("row.className='agent-row'",text)
        self.assertIn('AGENT_COLORS',text)

    def test_selected_agent_uses_private_session_prefix_and_base(self):
        text=Path("frontend/index.html").read_text(encoding="utf-8")
        self.assertIn('session_id:agentSession(activePersistentAgent)',text)
        self.assertIn("activePersistentAgent?.base||agentType.value",text)
        self.assertIn("agentChatViews",text)

    def test_sidebar_delete_uses_approval_protected_chat_command(self):
        text=Path("frontend/index.html").read_text(encoding="utf-8")
        self.assertIn('sendMessage(`Delete agent ${a.name}`)',text)
        self.assertNotIn("fetch(`/agents/${a.id}`",text)


if __name__ == "__main__":
    unittest.main()
