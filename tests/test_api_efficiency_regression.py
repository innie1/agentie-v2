import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agentie.core import agent_registry, deep_research, runner, team_orchestrator


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


if __name__=='__main__':unittest.main()
