import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agentie.core import native_last30days
from agentie.core.external_skill_runtime import LAST30_REPO, LAST30_SCRIPT, last30days_status
from agentie.core.skill_registry import all_skills, route_skill_command


class Last30DaysSkillRegressionTests(unittest.TestCase):
    def test_skill_defaults_to_native_python311_runtime(self):
        skill=all_skills()['last30days']
        self.assertEqual(skill.get('kind'),'native_external_compatible')
        self.assertEqual(skill.get('repository'),LAST30_REPO)
        self.assertIn('recent_research',skill.get('capabilities',[]))
        self.assertTrue(skill['runtime']['ready'])
        self.assertEqual(skill['runtime']['python'],'3.11+')

    def test_native_engine_has_real_multi_source_lanes(self):
        names=[name for name,_ in native_last30days.SOURCE_LANES]
        for expected in ('reddit','x','youtube','hackernews','github','web'):
            self.assertIn(expected,names)

    def test_native_status_command_does_not_require_python312(self):
        result=route_skill_command('Last30Days status')
        self.assertIn('Python 3.11+',result['message'])
        self.assertTrue(result['card']['status']['ready'])
        self.assertEqual(result['card']['status']['engine'],'Agentie native')

    def test_native_research_works_without_provider_using_gathered_sources(self):
        sources=[{'id':'L1','source':'reddit','title':'Users discuss agents','url':'https://reddit.com/r/example/1','domain':'reddit.com','snippet':'People are testing more local agents.'}]
        with patch.object(native_last30days,'gather',return_value=sources), patch.object(native_last30days,'answer_web_search',new=AsyncMock(side_effect=RuntimeError('quota'))):
            result=native_last30days.run('AI agents')
        self.assertEqual(result['card']['type'],'last30days')
        self.assertEqual(result['card']['engine'],'native')
        self.assertEqual(result['card']['provider_calls'],0)
        self.assertIn('Users discuss agents',result['message'])

    def test_upstream_runtime_remains_optional_and_real(self):
        status=last30days_status()
        if status['ready']:
            self.assertTrue(status['installed']);self.assertIsNotNone(status['python'])
        text=Path('agentie/core/external_skill_runtime.py').read_text(encoding='utf-8')
        self.assertIn('git", "clone"',text)
        self.assertIn('last30days.py',text)
        self.assertIn('--emit=compact',text)
        self.assertIn('Python 3.12+',text)

    def test_normal_command_routes_native_before_optional_upstream(self):
        fake={'message':'native result','card':{'type':'last30days','engine':'native'}}
        with patch('agentie.core.skill_registry.route_native_last30days',return_value=fake), patch('agentie.core.skill_registry.route_last30days') as upstream:
            result=route_skill_command('Last30Days AI coding agents')
        self.assertEqual(result['card']['engine'],'native');upstream.assert_not_called()


if __name__=='__main__':unittest.main()
