import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import agent_registry,agent_teams,agent_threads,platform_router,routine_engine,team_orchestrator


class AgentTeamExecutionRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);self.root=Path(self.temp.name)
        self.patches=[
            patch.object(agent_registry,'WORKSPACE',self.root),patch.object(agent_registry,'AGENTS_FILE',self.root/'agents.json'),
            patch.object(agent_teams,'WORKSPACE',self.root),patch.object(agent_teams,'TEAMS',self.root/'agent_teams.json'),
            patch.object(agent_threads,'WORKSPACE',self.root),patch.object(agent_threads,'THREADS',self.root/'agent_threads.json'),
            patch.object(team_orchestrator,'WORKSPACE',self.root),patch.object(team_orchestrator,'TEAM_FILE',self.root/'team_jobs.json'),
            patch.object(routine_engine,'WORKSPACE',self.root),patch.object(routine_engine,'ROUTINES',self.root/'routines.json'),patch.object(routine_engine,'RUNS',self.root/'routine_runs.json'),
        ]
        for item in self.patches:item.start()
    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.temp.cleanup()

    def test_user_can_run_real_parallel_team_job_from_user_created_team(self):
        a=agent_registry.create_agent('Ada','Customer support owner')['agent'];b=agent_registry.create_agent('Ben','Follow-up owner')['agent'];team=agent_teams.create_team('Customer Ops',[a['id'],b['id']])
        with patch('agentie.core.team_orchestrator.start_team_job') as start:
            result=agent_teams.run_team_task(team['id'],'Review today’s customer issues')
        self.assertEqual(set(result['job']['agent_ids']),{a['id'],b['id']});self.assertEqual(result['card']['type'],'team_job');start.assert_called_once_with(result['job']['id'])

    def test_natural_team_task_command_uses_team_job_engine(self):
        a=agent_registry.create_agent('Ada','Support owner')['agent'];b=agent_registry.create_agent('Ben','Follow-up owner')['agent'];agent_teams.create_team('Customer Ops',[a['id'],b['id']])
        with patch('agentie.core.team_orchestrator.start_team_job'):
            result=agent_teams.route_team_structure_command('Have team Customer Ops work on review customer complaints')
        self.assertEqual(result['card']['type'],'team_job');self.assertIn('Started team job',result['message'])

    def test_team_structure_router_never_steals_team_chat_commands(self):
        self.assertIsNone(agent_teams.route_team_structure_command('Show team chat Customer Ops'))
        self.assertIsNone(agent_teams.route_team_structure_command('Open team job team_123'))

    def test_chat_event_routine_can_have_real_owner_agent(self):
        agent=agent_registry.create_agent('Ada','Support owner')['agent']
        result=platform_router.route_platform_command('Create a routine called Watch Replies that when an agent reply summarize it for agent Ada')
        self.assertEqual(result['card']['trigger_type'],'event');self.assertEqual(result['card']['event_type'],'agent_thread.agent_reply');self.assertEqual(result['card']['owner_agent_id'],agent['id'])

    def test_team_goal_and_instructions_change_context_not_permissions(self):
        agent=agent_registry.create_agent('Ada','Support owner')['agent'];team=agent_teams.create_team('Customer Ops',[agent['id']])
        agent_teams.update_team(team['id'],goal='Reduce response time',instructions='Share final results in the team thread.')
        context=agent_teams.team_context(agent);fresh=agent_registry.get_agent(agent['id'])
        self.assertIn('Reduce response time',context);self.assertIn('Share final results',context);self.assertFalse(fresh['permissions']['delegate'])


if __name__=='__main__':unittest.main()
