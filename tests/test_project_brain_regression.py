import tempfile,unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import project_brain
from agentie.core.project_skills import activate,catalog

class ProjectBrainRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.file=Path(self.tmp.name)/"projects.json";self.patch=patch.object(project_brain,"PROJECTS_FILE",self.file);self.patch.start()
    def tearDown(self):self.patch.stop();self.tmp.cleanup()
    def test_long_running_novel_becomes_project(self):
        result=project_brain.route_project_command("I'm writing a novel for the next month")
        self.assertEqual(result["card"]["type"],"project");self.assertEqual(result["card"]["kind"],"novel");self.assertEqual(result["card"]["skill"],"novel-writing")
    def test_project_context_activates_skill_without_private_worker_chat(self):
        p=project_brain.create_project("Church app","Build an app for churches","app")
        project_brain.append_project_item(p["id"],"decisions","Mobile first")
        ctx=project_brain.project_context(project_brain.get_project(p["id"]),"coder","Implement onboarding")
        self.assertIn("ACTIVATED SKILL",ctx);self.assertIn("Product Building",ctx);self.assertIn("Mobile first",ctx);self.assertIn("Do not import another specialist's private conversation",ctx)
    def test_worker_result_is_distilled_not_full_unbounded_chat(self):
        p=project_brain.create_project("App","Build app","app");project_brain.record_worker_result(p["id"],"Mira","researcher","market research","x "*2000)
        saved=project_brain.get_project(p["id"]);self.assertLessEqual(len(saved["summaries"][-1]["value"]),900)
    def test_project_skills_use_progressive_activation(self):
        self.assertGreaterEqual(len(catalog()),6);skill=activate("screenwriting");self.assertIn("scene",skill["instructions"].lower())

if __name__=="__main__":unittest.main()
