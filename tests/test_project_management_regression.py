import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import project_brain
from agentie.tools import approval_tools


class ProjectManagementRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        self.p1=patch.object(project_brain,"PROJECTS_FILE",root/"projects.json")
        self.p2=patch.object(approval_tools,"STORE",root/"approvals.json")
        self.p1.start();self.p2.start()
    def tearDown(self):
        self.p2.stop();self.p1.stop();self.tmp.cleanup()

    def test_project_card_exposes_editable_context_sections(self):
        p=project_brain.create_project("Church App","Build a church app","app")
        project_brain.route_project_command(f"Add to project {p['id']} context: Churches need WhatsApp onboarding")
        project_brain.route_project_command(f"Add to project {p['id']} decision: Use Supabase")
        project_brain.route_project_command(f"Add to project {p['id']} milestone: Finish onboarding")
        card=project_brain.project_card(project_brain.get_project(p['id']))
        self.assertIn("Churches need WhatsApp onboarding",card["context"])
        self.assertIn("Use Supabase",card["decisions"])
        self.assertIn("Finish onboarding",card["milestones"])

    def test_project_can_be_renamed_and_goal_changed(self):
        p=project_brain.create_project("Church App","Build the first version","app")
        renamed=project_brain.route_project_command(f"Rename project {p['id']} to Shepherd")
        self.assertEqual(renamed["card"]["name"],"Shepherd")
        updated=project_brain.route_project_command(f"Set project {p['id']} goal to Launch to ten churches")
        self.assertEqual(updated["card"]["goal"],"Launch to ten churches")

    def test_delete_without_name_returns_selectable_project_picker(self):
        project_brain.create_project("One","First project","general")
        project_brain.create_project("Two","Second project","general")
        result=project_brain.route_project_command("Delete project")
        self.assertEqual(result["card"]["type"],"project_delete_picker")
        self.assertEqual(len(result["card"]["items"]),2)

    def test_project_delete_requires_approval_and_executes_only_after_approval(self):
        p=project_brain.create_project("Church App","Build a church app","app")
        result=project_brain.route_project_command(f"Delete project {p['id']}")
        self.assertIsNotNone(project_brain.get_project(p['id']))
        item=result["card"]["items"][0]
        self.assertEqual(item["metadata"]["kind"],"project_delete")
        approval_tools.resolve_approval(item["id"],True)
        self.assertIsNone(project_brain.get_project(p['id']))

    def test_project_ui_has_non_json_management_controls(self):
        ui=Path("frontend/plugin_access.js").read_text(encoding="utf-8")
        self.assertIn("project-manager-card",ui)
        self.assertIn("project_delete_picker",ui)
        self.assertIn("Delete selected",ui)
        self.assertIn("Add context",ui)
        self.assertIn("Change goal",ui)


if __name__=="__main__":unittest.main()
