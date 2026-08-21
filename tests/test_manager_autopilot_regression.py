import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import agent_registry, manager_autopilot, specialty_router, team_orchestrator


class ManagerAutopilotRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        root=Path(self.tmp.name)
        self.agent_patch=patch.object(agent_registry,'AGENTS_FILE',root/'agents.json')
        self.team_patch=patch.object(team_orchestrator,'TEAM_FILE',root/'team_jobs.json')
        self.agent_patch.start();self.team_patch.start()
        self.ceo=agent_registry.create_agent('CEO','CEO','manager')['agent']
        self.mira=agent_registry.create_agent('Mira','critic','research')['agent']
        self.alex=agent_registry.create_agent('Alex','CTO','coding')['agent']
        self.vera=agent_registry.create_agent('Vera','verifier','research')['agent']
        self.writer=agent_registry.create_agent('Content Writer','content writer','general')['agent']

    def tearDown(self):
        self.team_patch.stop();self.agent_patch.stop();self.tmp.cleanup()

    def test_complex_manager_goal_builds_specialist_chain(self):
        plan=manager_autopilot.build_autopilot_plan(
            'Build a church management app, research the market, implement it and verify launch readiness.',self.ceo)
        self.assertIsNotNone(plan)
        phases=[x['phase'] for x in plan['steps']]
        self.assertEqual(phases,['research','coding','verification'])
        self.assertEqual(plan['steps'][0]['agent']['name'],'Mira')
        self.assertEqual(plan['steps'][1]['agent']['name'],'Alex')
        self.assertEqual(plan['steps'][2]['agent']['name'],'Vera')

    def test_non_manager_does_not_trigger_autopilot(self):
        session=f"{self.mira['session_prefix']}main"
        self.assertIsNone(manager_autopilot.maybe_manager_autopilot(
            'Build a church management app, research it, implement it and verify it.',session))

    def test_configured_team_job_is_sequential_and_phase_specific(self):
        plan=manager_autopilot.build_autopilot_plan(
            'Build a church management app, research competitors, implement it and verify readiness.',self.ceo)
        job=team_orchestrator.create_team_job(plan['goal'],[x['agent'] for x in plan['steps']],requested_by=self.ceo['id'])
        configured=manager_autopilot._configure_team_job(job['id'],plan)
        hs=configured['handoffs']
        self.assertTrue(configured['autopilot'])
        self.assertEqual([h['autopilot_phase'] for h in hs],['research','coding','verification'])
        self.assertEqual(hs[0]['depends_on'],[])
        self.assertEqual(hs[1]['depends_on'],[hs[0]['id']])
        self.assertEqual(hs[2]['depends_on'],[hs[1]['id']])
        self.assertIn('Research the evidence',hs[0]['task'])
        self.assertIn('technical architecture',hs[1]['task'])
        self.assertIn('Verify the previous specialist',hs[2]['task'])

    def test_dependency_context_contains_only_predecessor_result(self):
        plan=manager_autopilot.build_autopilot_plan(
            'Build a church management app, research competitors, implement it and verify readiness.',self.ceo)
        job=team_orchestrator.create_team_job(plan['goal'],[x['agent'] for x in plan['steps']],requested_by=self.ceo['id'])
        configured=manager_autopilot._configure_team_job(job['id'],plan)
        first,second,third=configured['handoffs']
        previous={**first,'status':'completed','result':'MIRA PRIVATE RESEARCH RESULT'}
        manager_autopilot._inject_dependency(job['id'],second['id'],previous,plan['goal'])
        latest=team_orchestrator.get_team_job(job['id'])
        coding=next(h for h in latest['handoffs'] if h['id']==second['id'])
        verifier=next(h for h in latest['handoffs'] if h['id']==third['id'])
        brief=coding['context']['scoped_brief']
        self.assertIn('MIRA PRIVATE RESEARCH RESULT',brief)
        self.assertIn('only this dependency is shared',brief)
        self.assertNotIn('scoped_brief',verifier['context'])

    def test_artifact_compound_requests_stay_on_existing_job_engine(self):
        self.assertIsNone(manager_autopilot.build_autopilot_plan(
            'Research church management apps and then create a PDF report.',self.ceo))

    def test_natural_create_goal_reaches_autopilot_before_old_create_guard(self):
        session=f"{self.ceo['session_prefix']}main"
        sentinel={'message':'autopilot','card':{'type':'team_job'}}
        with patch('agentie.core.manager_autopilot.maybe_manager_autopilot',return_value=sentinel) as routed:
            result=specialty_router.maybe_auto_delegate('Create a launch campaign with research, content and verification.',session)
        self.assertIs(result,sentinel)
        routed.assert_called_once()


if __name__=='__main__':unittest.main()
