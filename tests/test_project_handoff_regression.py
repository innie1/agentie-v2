import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from agentie.core import project_brain,team_orchestrator

class ProjectHandoffRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        self.p1=patch.object(project_brain,"PROJECTS_FILE",root/"projects.json");self.p2=patch.object(team_orchestrator,"TEAM_FILE",root/"teams.json");self.p1.start();self.p2.start()
    def tearDown(self):self.p2.stop();self.p1.stop();self.tmp.cleanup()
    def test_team_job_carries_scoped_project_brief(self):
        p=project_brain.create_project("Agentie app","Build an app","app")
        agents=[{"id":"agt_r","name":"Research","role":"researcher","base":"research"},{"id":"agt_c","name":"Coder","role":"coder","base":"coding"}]
        job=team_orchestrator.create_team_job("Research the onboarding",agents,project_id=p["id"])
        self.assertEqual(job["project_id"],p["id"]);self.assertIn("ACTIVATED SKILL",job["handoffs"][0]["context"]["scoped_brief"]);self.assertIn("YOUR ASSIGNMENT",job["handoffs"][1]["context"]["scoped_brief"])
    def test_team_card_exposes_project_without_worker_private_chat(self):
        p=project_brain.create_project("Novel","Write a novel","novel");a={"id":"agt_w","name":"Writer","role":"writer","base":"general"};job=team_orchestrator.create_team_job("Draft chapter one",[a],project_id=p["id"]);card=team_orchestrator.team_job_card(job)
        self.assertEqual(card["project_id"],p["id"]);self.assertNotIn("context",card["handoffs"][0])

if __name__=="__main__":unittest.main()
