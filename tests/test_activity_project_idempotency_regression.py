import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import agent_registry, deletion_registry, project_brain


class ActivityProjectIdempotencyRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patches = [
            patch.object(project_brain, "PROJECTS_FILE", root / "projects.json"),
            patch.object(agent_registry, "AGENTS_FILE", root / "agents.json"),
            patch.object(agent_registry, "WORKSPACE", root),
            patch.object(deletion_registry, "DELETIONS_FILE", root / "deletions.json"),
        ]
        for item in self.patches:item.start()

    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.tmp.cleanup()

    def test_deleted_project_is_not_deleted_twice(self):
        project = project_brain.create_project("Church App", "Build an app for churches", "app")
        first = project_brain.delete_project(project["id"])
        second = project_brain.delete_project(project["id"])
        self.assertEqual(first["name"], "Church App")
        self.assertTrue(second["already_deleted"])
        routed = project_brain._delete_request("Church App")
        self.assertEqual(routed["card"]["type"], "already_deleted")
        self.assertIn("Already deleted", routed["message"])

    def test_deleted_agent_returns_already_deleted_on_repeat(self):
        created = agent_registry.create_agent("Mira", "critic")["agent"]
        with patch("agentie.core.memory_store.purge_agent_memory", return_value={}), patch("agentie.core.agent_prompt.purge_instruction_profile", return_value=0):
            first = agent_registry.delete_agent(created["id"])
            second = agent_registry.delete_agent(created["id"])
        self.assertTrue(first["deleted"])
        self.assertTrue(second["already_deleted"])
        self.assertFalse(second["deleted"])

    def test_assigned_agent_gets_task_and_scoped_context_only(self):
        project = project_brain.create_project("Church App", "Build a church management application", "app")
        project_brain.append_project_item(project["id"], "decisions", "Use Supabase")
        project_brain.append_project_item(project["id"], "knowledge", "Pastors need WhatsApp onboarding", {"audience": "researcher"})
        mira = {"id": "agt_mira", "name": "Mira", "role": "researcher", "base": "research"}
        project_brain.assign_agents(project["id"], [mira])
        current = project_brain.get_project(project["id"])
        brief = project_brain.project_context(current, "researcher", "Research competing church apps")
        project_brain.set_agent_work(project["id"], mira, "Research competing church apps", "team_123", "CEO", "queued", brief)
        card = project_brain.project_card(project_brain.get_project(project["id"]), mira["id"])
        self.assertEqual(card["viewer_assignment"]["task"], "Research competing church apps")
        self.assertIn("Pastors need WhatsApp onboarding", card["viewer_assignment"]["scoped_brief"])
        self.assertEqual(card["decisions"], [])
        self.assertEqual(card["context"], [])
        self.assertEqual(card["milestones"], [])

    def test_frontend_has_activity_ranking_scoped_project_and_auto_scroll(self):
        raw = (Path(__file__).parents[1] / "frontend" / "events.js").read_text(encoding="utf-8")
        self.assertIn("agent-activity-dot", raw)
        self.assertIn("activityRank", raw)
        self.assertIn("chat.scrollTo({top:chat.scrollHeight", raw)
        self.assertIn("Your delegated task", raw)
        self.assertIn("Context for your work", raw)
        self.assertIn("Already deleted", raw)


if __name__ == "__main__":
    unittest.main()
