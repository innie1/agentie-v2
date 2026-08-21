import asyncio
import tempfile
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
        async def scenario():
            both_started=asyncio.Event();started=[]
            async def fake_worker(job_id,handoff):
                started.append(handoff["id"])
                if len(started)>=2:both_started.set()
                await asyncio.wait_for(both_started.wait(),timeout=.25)
                return handoff["id"],handoff["to_agent_name"]+" done",None
            with patch.object(team_orchestrator,"_worker",side_effect=fake_worker):
                await team_orchestrator._execute(job["id"])
            return started
        started=asyncio.run(scenario())
        finished=team_orchestrator.get_team_job(job["id"])
        self.assertEqual(len(started),2)
        self.assertEqual(finished["status"],"completed")
        self.assertTrue(all(h["status"]=="completed" for h in finished["handoffs"]))

    def test_partial_status_when_one_worker_fails(self):
        job=team_orchestrator.create_team_job("Mixed result",[self.alex,self.writer])
        async def fake_worker(job_id,handoff):
            if handoff["to_agent_name"]=="Writer":return handoff["id"],None,"usage limit"
            return handoff["id"],"Alex result",None
        with patch.object(team_orchestrator,"_worker",side_effect=fake_worker):asyncio.run(team_orchestrator._execute(job["id"]))
        finished=team_orchestrator.get_team_job(job["id"])
        self.assertEqual(finished["status"],"partial")
        self.assertIn("Alex result",finished["final_output"])

    def test_failed_worker_can_retry_without_restarting_successful_worker(self):
        job=team_orchestrator.create_team_job("Retry test",[self.alex,self.writer])
        ids={h["to_agent_name"]:h["id"] for h in job["handoffs"]}
        team_orchestrator._finish_job(job["id"],[(ids["Alex"],"done",None),(ids["Writer"],None,"limit")])
        with patch.object(team_orchestrator,"start_team_job") as start:
            retried=team_orchestrator.retry_team_worker(job["id"],"Writer")
        self.assertEqual(next(h for h in retried["handoffs"] if h["to_agent_name"]=="Alex")["status"],"completed")
        self.assertEqual(next(h for h in retried["handoffs"] if h["to_agent_name"]=="Writer")["status"],"queued")
        start.assert_called_once_with(job["id"],{ids["Writer"]})

    def test_missing_agent_offers_create_or_similar_agent_instead_of_phantom(self):
        before=len(agent_registry.list_agents())
        result=route_role_command("Delegate write the launch post to Content Writer")
        self.assertEqual(result["card"]["type"],"agent_choice")
        self.assertEqual(result["card"]["missing_agent"],"Content Writer")
        actions=[x["action"] for x in result["card"]["options"]]
        self.assertIn("create_agent",actions);self.assertIn("use_agent",actions)
        self.assertEqual(len(agent_registry.list_agents()),before)

    def test_state_of_that_task_uses_backend_status_without_provider_calls(self):
        job=team_orchestrator.create_team_job("Review launch readiness",[self.alex,self.writer])
        team_orchestrator._mutate(job["id"],lambda j:[h.update(status="working") for h in j["handoffs"]])
        with patch("agentie.core.runner.run_agent",side_effect=AssertionError("status must stay local")) as provider:
            result=route_role_command("What's the state of that task?")
        provider.assert_not_called()
        self.assertEqual(result["card"]["id"],job["id"])
        self.assertEqual(result["card"].get("status_source"),"backend")
        summaries={h["agent"]:h["summary"] for h in result["card"]["handoffs"]}
        self.assertIn("Still working",summaries["Alex"]);self.assertIn("Still working",summaries["Writer"])
        self.assertTrue(result["card"].get("status_checked_at"))

    def test_worker_status_helper_is_provider_free_and_truthful(self):
        job=team_orchestrator.create_team_job("Review launch readiness",[self.alex])
        handoff=job["handoffs"][0];handoff["status"]="working"
        with patch("agentie.core.runner.run_agent",side_effect=AssertionError("must not be called")) as provider:
            hid,summary=asyncio.run(team_orchestrator._ask_worker_status(job,handoff))
        provider.assert_not_called()
        self.assertEqual(hid,handoff["id"]);self.assertIn("Still working",summary);self.assertIn("no completed result",summary)


if __name__=="__main__":unittest.main()
