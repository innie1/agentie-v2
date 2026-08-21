import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agentie.core import agent_registry, deep_research, memory_store, runner, team_orchestrator


class ApiEfficiencyRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        self.old_agents=agent_registry.AGENTS_FILE;self.old_agent_workspace=agent_registry.WORKSPACE
        self.old_team=team_orchestrator.TEAM_FILE;self.old_team_workspace=team_orchestrator.WORKSPACE
        agent_registry.WORKSPACE=root;agent_registry.AGENTS_FILE=root/'agents.json'
        team_orchestrator.WORKSPACE=root;team_orchestrator.TEAM_FILE=root/'team_jobs.json'
        self.worker=agent_registry.create_agent('Mira','critic','research')['agent']
        runner._PROVIDER_COOLDOWNS.clear()

    def tearDown(self):
        runner._PROVIDER_COOLDOWNS.clear()
        agent_registry.AGENTS_FILE=self.old_agents;agent_registry.WORKSPACE=self.old_agent_workspace
        team_orchestrator.TEAM_FILE=self.old_team;team_orchestrator.WORKSPACE=self.old_team_workspace
        self.temp.cleanup()

    def test_team_status_uses_authoritative_backend_state_without_provider_call(self):
        job=team_orchestrator.create_team_job('Research market',[self.worker])
        team_orchestrator._mutate(job['id'],lambda j:j['handoffs'][0].update(status='working'))
        with patch('agentie.core.runner.run_agent',side_effect=AssertionError('status must not call provider')) as call:
            current=team_orchestrator.request_team_status(job['id'])
        call.assert_not_called()
        self.assertEqual(current.get('status_source'),'backend')
        self.assertIn('Still working',current['handoffs'][0]['progress_summary'])

    def test_usage_limit_starts_cooldown_and_next_turn_does_not_hit_provider(self):
        info={'provider':'gemini','model':'test-model'}
        with patch.object(runner,'get_provider_info',return_value=info), patch.object(runner,'build_assistant',return_value=object()), patch.object(runner.Runner,'run',new=AsyncMock(side_effect=RuntimeError('429 quota exceeded'))) as first:
            with self.assertRaisesRegex(RuntimeError,'usage limit'):
                asyncio.run(runner.run_agent('hard task','general',None))
            self.assertEqual(first.await_count,1)
        self.assertIsNotNone(runner.provider_cooldown(info))
        with patch.object(runner,'get_provider_info',return_value=info), patch.object(runner.Runner,'run',new=AsyncMock(return_value=None)) as second:
            with self.assertRaisesRegex(RuntimeError,'suppressing repeated provider calls'):
                asyncio.run(runner.run_agent('another hard task','general',None))
            self.assertEqual(second.await_count,0)

    def test_deep_research_keeps_gathered_evidence_when_synthesis_provider_is_limited(self):
        source=deep_research.Source('S1','Church product','https://example.com','Useful pricing evidence','Useful pricing evidence and onboarding details','church apps')
        async def unavailable(*args,**kwargs):
            raise RuntimeError('The AI model is temporarily at its usage limit.')
        with patch.object(deep_research,'collect_sources',new=AsyncMock(return_value=(['church apps'],[source],[]))):
            result=asyncio.run(deep_research.run_deep_research('Church management apps',unavailable,'agent:test:main'))
        self.assertEqual(result['synthesis_mode'],'local_evidence_fallback')
        self.assertIn('Local evidence summary',result['report'])
        self.assertIn('[S1]',result['report'])
        self.assertIn('https://example.com',result['report'])

    def test_recent_prompt_history_is_individually_and_globally_bounded(self):
        raw=[
            {'role':'assistant','content':'A'*6000,'metadata':{},'created_at':'1'},
            {'role':'user','content':'B'*5000,'metadata':{},'created_at':'2'},
            {'role':'assistant','content':'C'*4000,'metadata':{},'created_at':'3'},
            {'role':'user','content':'short newest','metadata':{},'created_at':'4'},
        ]
        with patch.object(memory_store,'session_messages',return_value=raw):
            history=memory_store._prompt_history('agent:agt_test:main')
        self.assertTrue(history)
        self.assertLessEqual(sum(len(x['content']) for x in history),5200)
        self.assertTrue(all(len(x['content'])<=1400 for x in history))
        self.assertIn('short newest',[x['content'] for x in history])

    def test_bounded_handoff_prompt_does_not_pull_semantic_history(self):
        with patch.object(memory_store,'_bootstrap_semantic'), patch.object(memory_store,'_prompt_history',return_value=[]), patch('agentie.core.semantic_memory.search_memory') as semantic:
            prompt=memory_store.build_context_prompt('agent:agt_mira:handoff:team_123','Bounded worker brief')
        semantic.assert_not_called()
        self.assertEqual(prompt,'Bounded worker brief')

    def test_normal_semantic_memory_is_clipped_before_provider_prompt(self):
        hits={'hits':[{'kind':'message','score':.9,'text':'X'*9000},{'kind':'memory','score':.8,'text':'Y'*9000}]}
        with patch.object(memory_store,'_bootstrap_semantic'), patch.object(memory_store,'_prompt_history',return_value=[]), patch('agentie.core.semantic_memory.search_memory',return_value=hits):
            prompt=memory_store.build_context_prompt('agent:agt_mira:main','What did we decide?')
        self.assertIn('Relevant long-term memory',prompt)
        self.assertLess(len(prompt),2500)
        self.assertNotIn('X'*1000,prompt)


if __name__=='__main__':unittest.main()
