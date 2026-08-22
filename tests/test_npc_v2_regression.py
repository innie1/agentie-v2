import gc,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from agentie.core import agent_prompt,memory_store,npc_brain,team_orchestrator

class NPCV2RegressionTests(unittest.TestCase):
    def setUp(self):
        # SQLite connections created during the test can remain alive until GC on
        # Windows. Ignore cleanup races here; DB_PATH already isolates every test.
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);root=Path(self.temp.name)
        self.agent={"id":"agt_npcv2","name":"Alex","role":"CTO","purpose":"Lead engineering","permissions":{"capability_mode":"explicit"},"skills":[]}
        self.p1=patch.object(agent_prompt,"PROMPTS_FILE",root/"prompts.json");self.p1.start()
        self.p2=patch.object(memory_store,"DB_PATH",root/"memory.sqlite3");self.p2.start()
        self.p3=patch.object(team_orchestrator,"TEAM_FILE",root/"team_jobs.json");self.p3.start()
        self.session="agent:agt_npcv2:chat"
    def tearDown(self):
        self.p3.stop();self.p2.stop();self.p1.stop();gc.collect()
        # Retry briefly because sqlite/WAL handles can be released a moment after
        # the final connection object becomes unreachable on Windows.
        for _ in range(10):
            try:self.temp.cleanup();break
            except (PermissionError,NotADirectoryError,OSError):time.sleep(.05);gc.collect()
    def test_normal_conversation_is_local(self):
        r=npc_brain.try_npc_response(self.agent,"how are you",self.session);self.assertEqual(r["routed_by"],"npc_brain");self.assertGreaterEqual(r["confidence"],.9)
    def test_make_it_shorter_uses_previous_assistant_context_locally(self):
        memory_store.add_message(self.session,"assistant","This is a long explanation. It has another sentence with extra detail that is not needed for the short version.")
        r=npc_brain.try_npc_response(self.agent,"make it shorter",self.session);self.assertEqual(r["context_action"],"shorten_previous");self.assertIn("long explanation",r["message"])
    def test_failed_provider_turn_is_not_replaced_by_old_answer(self):
        memory_store.add_message(self.session,"assistant","Old successful answer.")
        memory_store.add_message(self.session,"user","Explain safe deployment")
        memory_store.set_context(self.session,"last_provider_failure",{"user_message":"Explain safe deployment","error":"usage limit"})
        r=npc_brain.try_npc_response(self.agent,"make it shorter",self.session);self.assertEqual(r["context_action"],"failed_previous_turn");self.assertIn("isn’t a successful answer",r["message"])
    def test_repeat_that_is_local(self):
        memory_store.add_message(self.session,"assistant","Use the existing route and preserve compatibility.")
        r=npc_brain.try_npc_response(self.agent,"repeat that",self.session);self.assertEqual(r["message"],"Use the existing route and preserve compatibility.")
    def test_do_that_resolves_context_but_escalates_actual_work(self):
        memory_store.add_message(self.session,"user","We could write the launch post next.");memory_store.add_message(self.session,"assistant","I can draft the launch post next.")
        r=npc_brain.try_npc_response(self.agent,"do that",self.session);self.assertIn("escalate_message",r);self.assertNotIn("message",r);self.assertIn("launch post",r["escalate_message"])
    def test_do_that_checks_active_handoff_instead_of_provider(self):
        writer={"id":"agt_writer","name":"Writer","role":"writer","purpose":"","base":"general"}
        job=team_orchestrator.create_team_job("write the launch post",[writer],requested_by=self.agent["id"])
        memory_store.set_context(self.session,"active_team_job_id",job["id"]);memory_store.set_context(self.session,"active_team_job_task",job["task"])
        r=npc_brain.try_npc_response(self.agent,"do that",self.session);self.assertEqual(r["context_action"],"active_team_job");self.assertIn("already in progress",r["message"]);self.assertNotIn("escalate_message",r)
    def test_continue_escalates_instead_of_pretending_completion(self):
        memory_store.add_message(self.session,"assistant","The first step is complete; the next step is implementation.")
        r=npc_brain.try_npc_response(self.agent,"continue",self.session);self.assertIn("escalate_message",r);self.assertEqual(r["routed_by"],"npc_context")
    def test_job_title_alone_does_not_create_critic_runtime_class(self):
        critic={**self.agent,"id":"agt_critic","name":"Mira","role":"critic"}
        self.assertEqual(npc_brain.role_profile(critic),"general")
        self.assertIsNone(npc_brain.try_npc_response(critic,"give me a checklist",self.session))
    def test_job_title_alone_does_not_create_verifier_runtime_class(self):
        verifier={**self.agent,"id":"agt_verify","name":"Vera","role":"verifier"}
        self.assertEqual(npc_brain.role_profile(verifier),"general")
        self.assertIsNone(npc_brain.try_npc_response(verifier,"give me a checklist",self.session))
    def test_explicit_capability_still_enables_local_specialized_behavior(self):
        coder={**self.agent,"skills":["code-execution"]}
        r=npc_brain.try_npc_response(coder,"give me a debug checklist",self.session)
        self.assertEqual(r["npc_role"],"coding");self.assertIn("regression",r["message"].lower())
    def test_complex_open_ended_work_still_falls_through(self):
        self.assertIsNone(npc_brain.try_npc_response(self.agent,"Design a complete distributed database architecture for a global banking platform",self.session))

if __name__=='__main__':unittest.main()
