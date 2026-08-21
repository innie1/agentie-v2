import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import job_engine, project_brain, reference_router, team_orchestrator
from agentie.core.npc_brain import job_title


class PinJobTitleDocumentDelegationRegressionTests(unittest.TestCase):
    def test_npc_generates_short_human_job_title_without_provider(self):
        title=job_title("Research the latest AI agent trends and write a report")
        self.assertEqual(title,"Latest AI Agent Trends Report")
        self.assertNotRegex(title,r"^[a-f0-9]{8,12}$")

    def test_job_card_keeps_internal_id_but_exposes_human_title(self):
        job={"id":"ab12cd34ef","goal":"Research the latest AI agent trends and write a report","status":"queued","completed_steps":0,"total_steps":1,"provider_calls":0,"budget_provider_calls":8,"final_output":None,"error":None,"steps":[]}
        card=job_engine.job_card(job)
        self.assertEqual(card["id"],"ab12cd34ef")
        self.assertEqual(card["title"],"Latest AI Agent Trends Report")
        self.assertEqual(card["goal"],card["title"])
        self.assertEqual(card["request"],job["goal"])

    def test_job_status_message_uses_title_not_internal_id(self):
        job={"id":"ab12cd34ef","goal":"Research the latest AI agent trends and write a report","status":"running","completed_steps":0,"total_steps":1,"provider_calls":0,"budget_provider_calls":8,"final_output":None,"error":None,"steps":[]}
        with patch("agentie.core.reference_router.get_context",return_value="ab12cd34ef"),patch("agentie.core.reference_router.set_context"),patch("agentie.core.job_engine.get_job",return_value=job):
            result=reference_router._job_command("session","Job status")
        self.assertIn("Latest AI Agent Trends Report",result["message"])
        self.assertNotIn("ab12cd34ef",result["message"])

    def test_sidebar_has_visible_pin_control_and_pinned_visual_order(self):
        raw=Path("frontend/index.html").read_text(encoding="utf-8")
        self.assertIn("agent-pin",raw)
        self.assertIn("pin.textContent='📌'",raw)
        self.assertIn("a.pinned?'Unpin':'Pin'",raw)
        self.assertIn("row.dataset.pinned",raw)
        self.assertIn("row.style.order=a.pinned",raw)
        self.assertIn("await loadPersistentAgents()",raw)

    def test_generated_document_cards_expose_human_document_name(self):
        office=Path("agentie/core/office_artifacts.py").read_text(encoding="utf-8")
        pdf=Path("agentie/core/pdf_service.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(office.count("'document_name':title"),3)
        self.assertIn("'document_name':title",pdf)
        self.assertIn("Created “{card.get('document_name')",office)
        self.assertIn("Created “{card.get('document_name')",pdf)

    def test_two_delegated_agents_receive_only_their_scoped_project_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            mira={"id":"agt_mira","name":"Mira","role":"researcher","base":"research","session_prefix":"agent:agt_mira:"}
            alex={"id":"agt_alex","name":"Alex","role":"coder","base":"coding","session_prefix":"agent:agt_alex:"}
            agents={"mira":mira,"alex":alex,"agt_mira":mira,"agt_alex":alex}
            with patch.object(project_brain,"PROJECTS_FILE",root/"projects.json"),patch.object(team_orchestrator,"TEAM_FILE",root/"team_jobs.json"),patch("agentie.core.agent_registry.get_agent",side_effect=lambda key:agents.get(str(key).casefold())):
                project=project_brain.create_project("Church App","Build a church management application","app")
                project_brain.append_project_item(project["id"],"knowledge","Compare church-management competitors, pricing and WhatsApp onboarding.",{"audience":"researcher"})
                project_brain.append_project_item(project["id"],"knowledge","Implement the approved architecture and Supabase integration.",{"audience":"coder"})
                job=team_orchestrator.create_team_job("Prepare the Church App launch plan",[mira,alex],project_id=project["id"])
                self.assertEqual(job["project_id"],project["id"])
                stored=project_brain.get_project(project["id"])
                mira_card=project_brain.project_card(stored,mira["id"])
                alex_card=project_brain.project_card(stored,alex["id"])
                self.assertEqual(mira_card["viewer_assignment"]["task"],"Prepare the Church App launch plan")
                self.assertEqual(alex_card["viewer_assignment"]["task"],"Prepare the Church App launch plan")
                mira_brief=mira_card["viewer_assignment"]["scoped_brief"]
                alex_brief=alex_card["viewer_assignment"]["scoped_brief"]
                self.assertIn("Compare church-management competitors",mira_brief)
                self.assertNotIn("Supabase integration",mira_brief)
                self.assertIn("Supabase integration",alex_brief)
                self.assertNotIn("Compare church-management competitors",alex_brief)

    def test_scoped_project_ui_shows_task_and_context_not_team_id_as_primary_content(self):
        raw=Path("frontend/events.js").read_text(encoding="utf-8")
        self.assertIn("Your delegated task",raw)
        self.assertIn("Context for your work",raw)
        self.assertIn("work.task",raw)
        self.assertIn("work.scoped_brief",raw)


if __name__=="__main__":
    unittest.main()
