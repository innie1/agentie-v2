import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import agent_registry, manager_autopilot, reference_router, specialty_router, team_orchestrator


class ManagerAutopilotRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        root=Path(self.tmp.name)
        self.agent_patch=patch.object(agent_registry,'AGENTS_FILE',root/'agents.json')
        self.team_patch=patch.object(team_orchestrator,'TEAM_FILE',root/'team_jobs.json')
        self.agent_patch.start();self.team_patch.start()
        self.ceo=agent_registry.create_agent('CEO','Company coordinator',purpose='Coordinate multi-agent company work',permissions={'delegate':True})['agent']
        self.mira=agent_registry.create_agent('Mira','Market and competitor research owner',purpose='Research competitors, requirements, market evidence and customer needs',responsibilities=['Research competitors and requirements','Collect market evidence'])['agent']
        self.alex=agent_registry.create_agent('Alex','Technical implementation owner',purpose='Implement apps, build software and create technical architecture',responsibilities=['Implement the application','Create technical implementation architecture'])['agent']
        self.vera=agent_registry.create_agent('Vera','Launch verification and QA owner',purpose='Verify launch readiness, test deliverables and find quality risks',responsibilities=['Verify launch readiness','Review completed implementation for risks'])['agent']
        self.writer=agent_registry.create_agent('Content Writer','Content owner',purpose='Write campaign and launch content')['agent']

    def tearDown(self):
        self.team_patch.stop();self.agent_patch.stop();self.tmp.cleanup()

    def _plan(self):
        return manager_autopilot.build_autopilot_plan(
            'Research competitors and requirements; implement the app technical architecture; then verify launch readiness.',self.ceo)

    def test_complex_manager_goal_builds_configured_agent_chain(self):
        plan=self._plan()
        self.assertIsNotNone(plan)
        self.assertEqual([x['phase'] for x in plan['steps']],['step_1','step_2','step_3'])
        self.assertEqual([x['agent']['name'] for x in plan['steps']],['Mira','Alex','Vera'])
        self.assertTrue(plan['sequential'])

    def test_job_titles_do_not_create_autopilot_authority(self):
        fake_manager=agent_registry.create_agent('Boss','Chief of Staff',purpose='Coordinate everything')['agent']
        plan=manager_autopilot.build_autopilot_plan(
            'Research competitors; implement the app; then verify launch readiness.',fake_manager)
        self.assertIsNone(plan)
        self.assertFalse(fake_manager['permissions']['delegate'])

    def test_non_delegating_agent_does_not_trigger_autopilot(self):
        session=f"{self.mira['session_prefix']}main"
        self.assertIsNone(manager_autopilot.maybe_manager_autopilot(
            'Research competitors; implement the app; then verify launch readiness.',session))

    def test_configured_team_job_is_sequential_and_uses_actual_agent_assignments(self):
        plan=self._plan()
        job=team_orchestrator.create_team_job(plan['goal'],[x['agent'] for x in plan['steps']],requested_by=self.ceo['id'])
        configured=manager_autopilot._configure_team_job(job['id'],plan)
        hs=configured['handoffs']
        self.assertTrue(configured['autopilot'])
        self.assertEqual(configured['autopilot_kind'],'configured_agent_plan')
        self.assertEqual([h['to_agent_name'] for h in hs],['Mira','Alex','Vera'])
        self.assertEqual(hs[0]['depends_on'],[])
        self.assertEqual(hs[1]['depends_on'],[hs[0]['id']])
        self.assertEqual(hs[2]['depends_on'],[hs[1]['id']])
        self.assertIn('Research competitors',hs[0]['task'])
        self.assertIn('implement the app',hs[1]['task'].lower())
        self.assertIn('verify launch readiness',hs[2]['task'].lower())

    def test_dependency_context_contains_only_predecessor_result(self):
        plan=self._plan()
        job=team_orchestrator.create_team_job(plan['goal'],[x['agent'] for x in plan['steps']],requested_by=self.ceo['id'])
        configured=manager_autopilot._configure_team_job(job['id'],plan)
        first,second,third=configured['handoffs']
        previous={**first,'status':'completed','result':'MIRA SCOPED RESEARCH RESULT'}
        manager_autopilot._inject_dependency(job['id'],second['id'],previous,plan['goal'])
        latest=team_orchestrator.get_team_job(job['id'])
        implementation=next(h for h in latest['handoffs'] if h['id']==second['id'])
        verifier=next(h for h in latest['handoffs'] if h['id']==third['id'])
        brief=implementation['context']['scoped_brief']
        self.assertIn('MIRA SCOPED RESEARCH RESULT',brief)
        self.assertIn('only this dependency is shared',brief)
        self.assertNotIn('scoped_brief',verifier['context'])

    def test_artifact_compound_requests_stay_on_existing_job_engine(self):
        prompts=(
            'Research church management apps and then create a PDF report.',
            'Research competitors and then create a PPTX presentation.',
            'Analyze the figures and then produce an XLSX spreadsheet.',
            'Research the requirements and then create a DOCX document.',
        )
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertIsNone(manager_autopilot.build_autopilot_plan(prompt,self.ceo))

    def test_simple_writing_request_is_not_expanded_into_autopilot(self):
        self.assertIsNone(manager_autopilot.build_autopilot_plan('Write the launch post.',self.ceo))

    def test_natural_create_goal_reaches_autopilot_before_old_create_guard(self):
        session=f"{self.ceo['session_prefix']}main"
        sentinel={'message':'autopilot','card':{'type':'team_job'}}
        with patch('agentie.core.manager_autopilot.maybe_manager_autopilot',return_value=sentinel) as routed:
            result=specialty_router.maybe_auto_delegate('Create a launch campaign with research, content and verification.',session)
        self.assertIs(result,sentinel)
        routed.assert_called_once()

    def test_reference_router_prioritizes_autopilot_over_implicit_deep_research_job(self):
        session=f"{self.ceo['session_prefix']}main"
        prompt='Research competitors and requirements; implement the app technical architecture; then verify launch readiness.'
        sentinel={'message':'Manager Autopilot started','card':{'type':'team_job','autopilot':True}}
        with patch('agentie.core.reference_router.get_context',return_value=None),patch('agentie.core.manager_autopilot.maybe_manager_autopilot',return_value=sentinel) as routed,patch('agentie.core.job_engine.create_job') as create:
            result=reference_router._job_command(session,prompt)
        self.assertEqual(result['routed_by'],'manager_autopilot')
        self.assertTrue(result['card']['autopilot'])
        routed.assert_called_once_with(prompt,session)
        create.assert_not_called()

    def test_reference_router_preserves_research_to_pdf_job_engine(self):
        session=f"{self.ceo['session_prefix']}main"
        prompt='Research Nigerian church management apps and after the research create a PDF with the research'
        fake={'id':'abc123','goal':prompt,'status':'queued','completed_steps':0,'total_steps':2,'provider_calls':0,'budget_provider_calls':8,'final_output':None,'error':None,'steps':[]}
        card={'type':'job_progress','id':'abc123','title':'Church Apps Report','goal':prompt}
        with patch('agentie.core.reference_router.get_context',return_value=None),patch('agentie.core.reference_router.set_context'),patch('agentie.core.manager_autopilot.maybe_manager_autopilot',return_value=None) as routed,patch('agentie.core.job_engine.create_job',return_value=fake) as create,patch('agentie.core.job_engine.start_job'),patch('agentie.core.job_engine.job_card',return_value=card):
            result=reference_router._job_command(session,prompt)
        self.assertEqual(result['routed_by'],'job')
        self.assertEqual(result['card']['type'],'job_progress')
        routed.assert_called_once_with(prompt,session)
        create.assert_called_once_with(session,prompt)

    def test_reference_router_does_not_turn_simple_writing_into_background_job(self):
        session=f"{self.ceo['session_prefix']}main"
        with patch('agentie.core.reference_router.get_context',return_value=None),patch('agentie.core.manager_autopilot.maybe_manager_autopilot',return_value=None),patch('agentie.core.job_engine.create_job') as create:
            result=reference_router._job_command(session,'Write the launch post.')
        self.assertIsNone(result)
        create.assert_not_called()


if __name__=='__main__':unittest.main()
