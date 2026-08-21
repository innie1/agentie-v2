import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import project_brain, reference_router


class ProjectDedupeTeamRecoveryRegressionTests(unittest.TestCase):
    def test_same_project_name_is_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(project_brain, "PROJECTS_FILE", Path(tmp) / "projects.json"):
                first = project_brain.create_project("Church App", "First goal", "app")
                second = project_brain.create_project("church app", "Second request", "app")
                self.assertEqual(first["id"], second["id"])
                self.assertEqual(len(project_brain.list_projects()), 1)

    def test_create_command_reports_existing_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(project_brain, "PROJECTS_FILE", Path(tmp) / "projects.json"):
                project_brain.create_project("Church App", "Build the app", "app")
                result = project_brain.route_project_command("Create a project called Church App to build another version")
                self.assertIn("already exists", result["message"].lower())
                self.assertIn("reused", result["message"].lower())
                self.assertEqual(len(project_brain.list_projects()), 1)

    def test_restart_recovers_only_unfinished_team_handoffs(self):
        job = {"id": "team_recover", "status": "working", "handoffs": [
            {"id": "h1", "status": "queued"},
            {"id": "h2", "status": "working"},
            {"id": "h3", "status": "completed"},
        ]}
        reference_router._JOBS_RESUMED = False
        with patch("agentie.core.job_engine.resume_unfinished"), \
             patch("agentie.core.routine_worker.start_routine_worker"), \
             patch("agentie.core.team_orchestrator.list_team_jobs", return_value=[job]), \
             patch("agentie.core.team_orchestrator.start_team_job") as start:
            reference_router._ensure_jobs_resumed()
        start.assert_called_once_with("team_recover", {"h1", "h2"})
        reference_router._JOBS_RESUMED = False


if __name__ == "__main__":
    unittest.main()
