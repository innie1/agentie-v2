import unittest
from pathlib import Path


class VisibleAgentHandoffChatRegressionTests(unittest.TestCase):
    def test_backend_exposes_only_persisted_handoff_chat_for_agent(self):
        raw=Path('main.py').read_text(encoding='utf-8')
        self.assertIn('@app.get("/agents/{agent_id}/handoff-chat")',raw)
        self.assertIn('recent_messages(session,limit=50,max_chars=100000)',raw)
        self.assertIn('{"project_handoff","project_handoff_result"}',raw)
        self.assertIn('get_agent(agent_id)',raw)

    def test_worker_mirrors_task_and_result_to_normal_agent_chat(self):
        raw=Path('agentie/core/team_orchestrator.py').read_text(encoding='utf-8')
        self.assertIn('f"{agent[\'session_prefix\']}main"',raw)
        self.assertIn('"project_handoff"',raw)
        self.assertIn('"project_handoff_result"',raw)
        self.assertIn('visible=f"Project handoff: {h[\'task\']}"',raw)

    def test_frontend_polls_selected_agent_handoff_chat(self):
        raw=Path('frontend/events.js').read_text(encoding='utf-8')
        self.assertIn('__agentieHandoffChatFeed',raw)
        self.assertIn('/handoff-chat',raw)
        self.assertIn("label.textContent='Delegated work'",raw)
        self.assertIn("item.role==='user'?'Delegated task'",raw)
        self.assertIn('setInterval(refresh,1300)',raw)

    def test_agent_profile_has_native_card_not_raw_json(self):
        raw=Path('frontend/events.js').read_text(encoding='utf-8')
        self.assertIn("card?.type==='agent_profile'||card?.type==='agent'",raw)
        self.assertIn('agent-profile-card',raw)
        self.assertIn("['Role',card.role||'general']",raw)
        self.assertIn("['Pinned',card.pinned?'Yes':'No']",raw)


if __name__=='__main__':
    unittest.main()
