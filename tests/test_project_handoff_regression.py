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
    def test_one_project_can_be_visible_to_multiple_assigned_agents(self):
        p=project_brain.create_project("Church App","Build a church management app","app")
        agents=[{"id":"agt_m","name":"Mira","role":"researcher"},{"id":"agt_v","name":"Vera","role":"verifier"}]
        project_brain.assign_agents(p["id"],agents);project_brain.assign_agents(p["id"],agents)
        self.assertEqual([x["id"] for x in project_brain.projects_for_agent("agt_m")],[p["id"]]);self.assertEqual([x["id"] for x in project_brain.projects_for_agent("agt_v")],[p["id"]])
        saved=project_brain.get_project(p["id"]);self.assertEqual(sorted(saved["assigned_agent_ids"]),["agt_m","agt_v"]);self.assertEqual(len(saved["assigned_agents"]),2)
    def test_project_delegation_assigns_every_recipient(self):
        p=project_brain.create_project("Church App","Build a church management app","app")
        agents={"Mira":{"id":"agt_m","name":"Mira","role":"researcher","base":"research"},"Vera":{"id":"agt_v","name":"Vera","role":"verifier","base":"research"}}
        with patch("agentie.core.agent_registry.get_agent",side_effect=lambda value:agents.get(str(value))),patch.object(team_orchestrator,"start_team_job",return_value=None):
            result=project_brain.route_project_command("Delegate project Church App to Mira and Vera")
        self.assertEqual(result["card"]["project_id"],p["id"]);self.assertEqual({x["id"] for x in project_brain.get_project(p["id"])["assigned_agents"]},{"agt_m","agt_v"})
    def test_frontend_loads_assigned_projects_when_switching_agents(self):
        text=(Path(__file__).parents[1]/"frontend"/"index.html").read_text(encoding="utf-8")
        self.assertIn("loadAgentProjects(activePersistentAgent)",text);self.assertIn("Show projects for ${agent.name}",text);self.assertIn("agent-projects-pinned",text);self.assertIn("c.type==='projects'",text)

if __name__=="__main__":unittest.main()
