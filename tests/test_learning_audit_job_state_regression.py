import asyncio,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from agentie.core import agent_prompt,job_engine

class LearningAuditJobStateRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.agent={"id":"agt_test","name":"Alex","role":"CTO","purpose":"","permissions":{"delegate":True},"skills":[]}
        self.p1=patch.object(agent_prompt,"PROMPTS_FILE",self.root/"prompts.json");self.p1.start()
        self.p2=patch.object(job_engine,"DB_PATH",self.root/"jobs.sqlite3");self.p2.start()
        self.p3=patch.object(job_engine,"WORKSPACE",self.root);self.p3.start()
    def tearDown(self):self.p3.stop();self.p2.stop();self.p1.stop();self.temp.cleanup()
    def test_explicit_preference_is_learned_and_audited(self):
        agent_prompt.learn_from_user_message(self.agent,"I prefer my replies to be concise")
        p=agent_prompt.get_instruction_profile(self.agent);self.assertEqual(p["communication"]["default_length"],"concise");self.assertTrue(p["learning_audit"]);self.assertEqual(p["learning_audit"][-1]["source"],"conversation")
    def test_temporary_request_is_not_permanent(self):
        agent_prompt.learn_from_user_message(self.agent,"Make this one reply concise")
        self.assertNotIn("default_length",agent_prompt.get_instruction_profile(self.agent)["communication"])
    def test_implicit_preference_requires_repetition(self):
        msg="Replies should be concise"
        agent_prompt.learn_from_user_message(self.agent,msg);self.assertNotIn("default_length",agent_prompt.get_instruction_profile(self.agent)["communication"])
        agent_prompt.learn_from_user_message(self.agent,msg);self.assertEqual(agent_prompt.get_instruction_profile(self.agent)["communication"]["default_length"],"concise")
    def test_instruction_card_contains_audit(self):self.assertIn("learning_audit",agent_prompt.instruction_card(self.agent))
    def test_pause_keeps_work_resumable(self):
        job=job_engine.create_job("agent:agt_test:chat","write launch plan")
        paused=job_engine.pause_job(job["id"]);self.assertEqual(paused["status"],"paused");self.assertTrue(all(x["status"]=="queued" for x in paused["steps"]))
    def test_resume_requeues_failed_steps(self):
        async def scenario():
            job=job_engine.create_job("agent:agt_test:chat","write launch plan")
            job_engine._set_step(job["id"],"s1",status="failed",error="temporary")
            async def runner(i,s,session):return "done"
            job_engine.resume_job(job["id"],runner);await asyncio.sleep(.05);return job_engine.get_job(job["id"])
        result=asyncio.run(scenario());self.assertEqual(result["status"],"completed")
    def test_agent_jobs_are_isolated(self):
        a=job_engine.create_job("agent:agt_test:chat","one");job_engine.create_job("agent:other:chat","two");ids={x["id"] for x in job_engine.jobs_for_agent("agt_test")};self.assertIn(a["id"],ids);self.assertEqual(len(ids),1)

if __name__=="__main__":unittest.main()
