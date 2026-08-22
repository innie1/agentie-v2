import gc,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import agent_registry,memory_store,npc_brain,specialty_router,team_orchestrator


class HandoffConsentRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);root=Path(self.temp.name)
        self.p_agents=patch.object(agent_registry,"AGENTS_FILE",root/"agents.json");self.p_agents.start()
        self.p_team=patch.object(team_orchestrator,"TEAM_FILE",root/"team_jobs.json");self.p_team.start()
        self.p_memory=patch.object(memory_store,"DB_PATH",root/"memory.sqlite3");self.p_memory.start()
        self.alex=agent_registry.create_agent("Alex","Engineering owner",purpose="Own technical implementation and engineering architecture")["agent"]
        self.writer=agent_registry.create_agent("Writer","Content and social media owner",purpose="Write social media posts, launch copy, blog posts and marketing content",responsibilities=["Write social media launch posts","Draft blog and campaign content"])["agent"]
        self.session=f"{self.alex['session_prefix']}main"
    def tearDown(self):
        self.p_memory.stop();self.p_team.stop();self.p_agents.stop();gc.collect()
        for _ in range(10):
            try:self.temp.cleanup();break
            except (PermissionError,NotADirectoryError,OSError):time.sleep(.05);gc.collect()
    def test_first_specialty_match_is_proposal_not_job(self):
        result=specialty_router.maybe_auto_delegate("write a social media post",self.session)
        self.assertEqual(result["card"]["type"],"agent_handoff_proposal")
        self.assertEqual(result["card"]["to_agent"]["id"],self.writer["id"])
        self.assertEqual(team_orchestrator.list_team_jobs(),[])
    def test_accept_starts_pending_handoff(self):
        specialty_router.maybe_auto_delegate("write a social media post",self.session)
        with patch.object(specialty_router,"start_team_job") as start:
            result=specialty_router.maybe_auto_delegate("Accept handoff",self.session)
        self.assertEqual(result["card"]["type"],"agent_handoff");start.assert_called_once()
        self.assertEqual(len(team_orchestrator.list_team_jobs()),1)
        self.assertTrue(memory_store.get_context(self.session,"active_team_job_id",""))
    def test_always_accept_persists_for_future_work_matching_same_configured_agent(self):
        specialty_router.maybe_auto_delegate("write a social media post",self.session)
        with patch.object(specialty_router,"start_team_job"):
            specialty_router.maybe_auto_delegate("Always accept handoff",self.session)
        key=specialty_router._agent_preference_key(self.alex["id"],self.writer["id"])
        self.assertEqual(memory_store.get_memory("routing",key),self.writer["id"])
        with patch.object(specialty_router,"start_team_job"):
            again=specialty_router.maybe_auto_delegate("draft a blog post for the launch",self.session)
        self.assertIsNotNone(again)
        self.assertEqual(again["card"]["type"],"agent_handoff")
        self.assertEqual(again["card"]["to_agent"]["id"],self.writer["id"])
    def test_retry_that_retries_active_failed_handoff_locally(self):
        job=team_orchestrator.create_team_job("write the launch post",[self.writer],requested_by=self.alex["id"])
        def fail(j):
            j["status"]="failed";j["handoffs"][0]["status"]="failed";j["handoffs"][0]["error"]="usage limit"
        team_orchestrator._mutate(job["id"],fail)
        memory_store.set_context(self.session,"active_team_job_id",job["id"]);memory_store.set_context(self.session,"active_team_job_task",job["task"])
        with patch.object(team_orchestrator,"start_team_job") as start:
            result=npc_brain.try_npc_response(self.alex,"retry that",self.session)
        self.assertEqual(result["context_action"],"retry_active_team_job")
        self.assertIn("Retrying Writer",result["message"]);start.assert_called_once()
        self.assertNotIn("escalate_message",result)
    def test_ui_exposes_accept_and_always_accept_buttons(self):
        text=(Path(__file__).parents[1]/"frontend"/"ui_upgrade.js").read_text(encoding="utf-8")
        self.assertIn("agent_handoff_proposal",text);self.assertIn("Accept handoff",text);self.assertIn("Always accept handoff",text)
        self.assertIn("accept.textContent='Accept'",text);self.assertIn("always.textContent='Always accept'",text)


if __name__=="__main__":unittest.main()
