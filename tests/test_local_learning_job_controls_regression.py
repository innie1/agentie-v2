import asyncio,unittest
from unittest.mock import patch
from pathlib import Path

from agentie.core import reference_router,role_store,runner


class LocalLearningJobControlsRegressionTests(unittest.TestCase):
    def test_runner_does_not_prelearn_then_fall_through_to_provider(self):
        text=Path('agentie/core/runner.py').read_text(encoding='utf-8')
        self.assertNotIn('learn_from_user_message(persistent_agent, message)',text)
        self.assertLess(text.index('try_npc_response'),text.index('get_provider_info()'))

    def test_preference_ack_can_return_before_provider(self):
        agent={'id':'agt_x','name':'Alex','role':'CTO','base':'manager','purpose':'','permissions':{},'skills':[]}
        async def go():
            with patch('agentie.core.runner.current_trace_id',return_value='trace'),patch('agentie.core.runner.agent_from_session',return_value=agent),patch('agentie.core.runner.try_npc_response',return_value={'message':'Got it. I’ll remember that.','routed_by':'npc_brain'}),patch('agentie.core.runner.add_message'),patch('agentie.core.runner.record_event'),patch('agentie.core.runner.get_provider_info') as provider:
                out=await runner.run_agent('I prefer concise replies','general','agent:agt_x:chat')
                provider.assert_not_called();return out
        self.assertIn('remember',asyncio.run(go()).lower())

    def test_pause_that_job_routes_locally(self):
        job={'id':'abc123','goal':'x','status':'paused','completed_steps':0,'total_steps':1,'provider_calls':0,'budget_provider_calls':8,'final_output':None,'error':None,'steps':[]}
        with patch('agentie.core.reference_router.get_context',return_value='abc123'),patch('agentie.core.job_engine.pause_job',return_value=job):
            result=reference_router._job_command('session','Pause that job')
        self.assertEqual(result['routed_by'],'job');self.assertIn('paused',result['message'].lower())

    def test_resume_that_job_routes_locally(self):
        job={'id':'abc123','goal':'x','status':'queued','completed_steps':0,'total_steps':1,'provider_calls':0,'budget_provider_calls':8,'final_output':None,'error':None,'steps':[]}
        with patch('agentie.core.reference_router.get_context',return_value='abc123'),patch('agentie.core.reference_router.set_context'),patch('agentie.core.job_engine.resume_job',return_value=job):
            result=reference_router._job_command('session','Resume that job')
        self.assertEqual(result['routed_by'],'job');self.assertIn('saved state',result['message'].lower())

    def test_show_active_jobs_is_local(self):
        job={'id':'abc123','goal':'x','status':'failed','completed_steps':0,'total_steps':1,'provider_calls':1,'budget_provider_calls':8,'final_output':None,'error':'limit','steps':[]}
        with patch('agentie.core.reference_router.get_context',return_value='abc123'),patch('agentie.core.job_engine.list_jobs',return_value=[job]):
            result=reference_router._job_command('session','Show my active jobs')
        self.assertEqual(result['card']['type'],'jobs');self.assertEqual(len(result['card']['items']),1)

    def test_manual_instruction_payload_strips_nested_command(self):
        value=role_store._manual_instruction_payload('Alex','Set Alex instructions to Always protect backwards compatibility.')
        self.assertEqual(value,'Always protect backwards compatibility.')


if __name__=='__main__':unittest.main()
