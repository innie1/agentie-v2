import asyncio
import unittest
from unittest.mock import AsyncMock,patch

from agentie.core import runner


class InternalHandoffNpcBypassRegressionTests(unittest.TestCase):
    def test_handoff_session_is_not_a_user_npc_turn(self):
        self.assertFalse(runner._npc_shortcuts_allowed('agent:mira:handoff:team_123'))
        self.assertFalse(runner._npc_shortcuts_allowed('handoff:team_123'))
        self.assertTrue(runner._npc_shortcuts_allowed('agent:mira:main'))
        self.assertTrue(runner._npc_shortcuts_allowed(None))

    def test_internal_handoff_reaches_model_without_npc_preference_ack(self):
        agent={
            'id':'agent_mira','name':'Mira','role':'critic','session_prefix':'agent:mira:',
            'permissions':{},'skills':[],
        }
        route={
            'mode':'auto','tier':'powerful','reason':'complex_task',
            'local_available':True,'cloud_configured':True,
            'task':{'score':2,'reasons':['multi_step_coordination']},
            'allow_cloud_fallback':False,
        }
        provider={'provider':'gemini','tier':'powerful','model':'cloud-model','base_url':'https://example.invalid'}
        attempt=AsyncMock(return_value='Hi from Mira.')
        with patch.object(runner,'current_trace_id',return_value='trace_test'), \
             patch.object(runner,'agent_from_session',return_value=agent), \
             patch.object(runner,'try_npc_response',side_effect=AssertionError('NPC must not inspect internal handoff prompts')) as npc, \
             patch.object(runner,'build_agent_instructions',return_value='Configured agent instructions.'), \
             patch.object(runner,'team_context',return_value=''), \
             patch.object(runner,'matching_workflow_skills',return_value=[]), \
             patch.object(runner,'build_context_prompt',side_effect=lambda _sid,msg:msg), \
             patch.object(runner,'choose_model_route',return_value=route), \
             patch.object(runner,'get_provider_info',return_value=provider), \
             patch.object(runner,'_attempt',new=attempt), \
             patch.object(runner,'add_message'), \
             patch.object(runner,'set_context'), \
             patch.object(runner,'record_event'):
            output=asyncio.run(runner.run_agent(
                'Internal group chat instruction containing: keep ordinary conversation concise.',
                'general',
                'agent:mira:handoff:team_123',
            ))
        self.assertEqual(output,'Hi from Mira.')
        npc.assert_not_called()
        self.assertEqual(attempt.await_count,1)


if __name__=='__main__':
    unittest.main()
