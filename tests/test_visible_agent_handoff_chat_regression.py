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

    def test_worker_syncs_working_completed_and_failed_into_project_brain(self):
        raw=Path('agentie/core/team_orchestrator.py').read_text(encoding='utf-8')
        self.assertIn('update_agent_work_status(pid,a["id"],"working")',raw)
        self.assertIn('record_worker_result(pid,a["name"]',raw)
        self.assertIn('update_agent_work_status(pid,a["id"],"failed"',raw)

    def test_frontend_polls_selected_agent_handoff_chat(self):
        raw=Path('frontend/events.js').read_text(encoding='utf-8')
        self.assertIn('__agentieHandoffChatFeed',raw)
        self.assertIn('/handoff-chat',raw)
        self.assertIn("label.textContent='Delegated work'",raw)
        self.assertIn("item.role==='user'?'Delegated task'",raw)
        self.assertIn('setInterval(refresh,1300)',raw)

    def test_final_project_renderer_preserves_scoped_assignment(self):
        raw=Path('frontend/plugin_access.js').read_text(encoding='utf-8')
        self.assertIn("title.textContent='Delegated work'",raw)
        self.assertIn("status.textContent=work.status||'assigned'",raw)
        self.assertIn("task.textContent=work.task||'Work on this project'",raw)
        self.assertIn("section(el,'Relevant decisions',card.decisions)",raw)
        self.assertIn("section(el,'Context for your work',card.context)",raw)
        self.assertIn("section(el,'Milestones',card.milestones)",raw)
        self.assertIn('work.latest_summary',raw)

    def test_scoped_open_does_not_fetch_global_project(self):
        raw=Path('frontend/plugin_access.js').read_text(encoding='utf-8')
        self.assertIn("if(p.viewer_assignment&&typeof window.addAssistant==='function')window.addAssistant('',p)",raw)
        self.assertIn("else projectCommand(`Show project ${p.id}`)",raw)

    def test_agent_profile_has_native_card_not_raw_json(self):
        raw=Path('frontend/events.js').read_text(encoding='utf-8')
        self.assertIn("card?.type==='agent_profile'||card?.type==='agent'",raw)
        self.assertIn('agent-profile-card',raw)
        self.assertIn("['Role',card.role||'general']",raw)
        self.assertIn("['Pinned',card.pinned?'Yes':'No']",raw)


if __name__=='__main__':
    unittest.main()
