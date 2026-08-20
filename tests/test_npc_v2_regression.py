import gc,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from agentie.core import agent_prompt,memory_store,npc_brain

class NPCV2RegressionTests(unittest.TestCase):
    def setUp(self):
        # SQLite connections created during the test can remain alive until GC on
        # Windows. Ignore cleanup races here; DB_PATH already isolates every test.
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);root=Path(self.temp.name)
        self.agent={"id":"agt_npcv2","name":"Alex","role":"CTO","purpose":"Lead engineering","permissions":{"delegate":True},"skills":[]}
        self.p1=patch.object(agent_prompt,"PROMPTS_FILE",root/"prompts.json");self.p1.start()
        self.p2=patch.object(memory_store,"DB_PATH",root/"memory.sqlite3");self.p2.start()
        self.session="agent:agt_npcv2:chat"
    def tearDown(self):
        self.p2.stop();self.p1.stop();gc.collect()
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
    def test_repeat_that_is_local(self):
        memory_store.add_message(self.session,"assistant","Use the existing route and preserve compatibility.")
        r=npc_brain.try_npc_response(self.agent,"repeat that",self.session);self.assertEqual(r["message"],"Use the existing route and preserve compatibility.")
    def test_do_that_resolves_context_but_escalates_actual_work(self):
        memory_store.add_message(self.session,"user","We could write the launch post next.");memory_store.add_message(self.session,"assistant","I can draft the launch post next.")
        r=npc_brain.try_npc_response(self.agent,"do that",self.session);self.assertIn("escalate_message",r);self.assertNotIn("message",r);self.assertIn("launch post",r["escalate_message"])
    def test_continue_escalates_instead_of_pretending_completion(self):
        memory_store.add_message(self.session,"assistant","The first step is complete; the next step is implementation.")
        r=npc_brain.try_npc_response(self.agent,"continue",self.session);self.assertIn("escalate_message",r);self.assertEqual(r["routed_by"],"npc_context")
    def test_critic_has_distinct_local_role_brain(self):
        critic={**self.agent,"id":"agt_critic","name":"Mira","role":"critic"}
        r=npc_brain.try_npc_response(critic,"give me a checklist",self.session);self.assertEqual(r["npc_role"],"critique");self.assertIn("failure modes",r["message"].lower())
    def test_verifier_has_distinct_local_role_brain(self):
        verifier={**self.agent,"id":"agt_verify","name":"Vera","role":"verifier"}
        r=npc_brain.try_npc_response(verifier,"give me a checklist",self.session);self.assertEqual(r["npc_role"],"verification");self.assertIn("verified",r["message"].lower())
    def test_complex_open_ended_work_still_falls_through(self):
        self.assertIsNone(npc_brain.try_npc_response(self.agent,"Design a complete distributed database architecture for a global banking platform",self.session))

if __name__=='__main__':unittest.main()
