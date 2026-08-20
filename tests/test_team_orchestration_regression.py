import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import agent_registry, team_orchestrator
from agentie.core.role_store import route_role_command


class TeamOrchestrationRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        self.old_agents=agent_registry.AGENTS_FILE;self.old_workspace=agent_registry.WORKSPACE
        self.old_team=team_orchestrator.TEAM_FILE;self.old_team_workspace=team_orchestrator.WORKSPACE
        agent_registry.WORKSPACE=root;agent_registry.AGENTS_FILE=root/"agents.json"
        team_orchestrator.WORKSPACE=root;team_orchestrator.TEAM_FILE=root/"team_jobs.json"
        self.alex=agent_registry.create_agent("Alex","CTO","manager")["agent"]
        self.writer=agent_registry.create_agent("Writer","Content Creator","general")["agent"]
    def tearDown(self):
        agent_registry.AGENTS_FILE=self.old_agents;agent_registry.WORKSPACE=self.old_workspace
        team_orchestrator.TEAM_FILE=self.old_team;team_orchestrator.WORKSPACE=self.old_team_workspace
        self.temp.cleanup()

    def test_handoff_stores_only_bounded_task_context(self):
        job=team_orchestrator.create_team_job("Prepare launch plan",[self.alex],requested_by="user")
        handoff=job["handoffs"][0]
        self.assertEqual(handoff["context"],{"task":"Prepare launch plan"})
        self.assertNotIn("memory",handoff["context"]);self.assertNotIn("chat",handoff["context"])

    def test_team_command_resolves_persistent_agents_without_duplicate_agents(self):
        with patch.object(team_orchestrator,"start_team_job"):
            result=route_role_command("Have Alex and Writer work together on prepare a launch plan")
        self.assertEqual(result["card"]["type"],"team_job")
        self.assertEqual(set(result["card"]["agents"]),{"Alex","Writer"})
        self.assertEqual(len(agent_registry.list_agents()),2)

    def test_delegate_command_creates_persistent_handoff(self):
        with patch.object(team_orchestrator,"start_team_job"):
            result=route_role_command("Delegate review the launch checklist to Alex")
        self.assertIn("Delegated",result["message"])
        job=team_orchestrator.get_team_job(result["card"]["id"])
        self.assertEqual(job["handoffs"][0]["to_agent_id"],self.alex["id"])

    def test_team_workers_are_scheduled_concurrently(self):
        job=team_orchestrator.create_team_job("Parallel test",[self.alex,self.writer])
        async def fake_worker(job_id,handoff):
            await asyncio.sleep(.12);return handoff["id"],handoff["to_agent_name"]+" done",None
        started=time.perf_counter()
        with patch.object(team_orchestrator,"_worker",side_effect=fake_worker):asyncio.run(team_orchestrator._execute(job["id"]))
        elapsed=time.perf_counter()-started
        finished=team_orchestrator.get_team_job(job["id"])
        self.assertLess(elapsed,.22)
        self.assertEqual(finished["status"],"completed")
        self.assertTrue(all(h["status"]=="completed" for h in finished["handoffs"]))

    def test_missing_agent_does_not_create_phantom_worker(self):
        before=len(agent_registry.list_agents())
        result=route_role_command("Delegate inspect the report to Nobody")
        self.assertIn("was not found",result["message"])
        self.assertEqual(len(agent_registry.list_agents()),before)


if __name__=="__main__":unittest.main()
