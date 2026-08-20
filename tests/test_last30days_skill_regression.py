import unittest
from pathlib import Path

from agentie.core.external_skill_runtime import LAST30_REPO, LAST30_SCRIPT, last30days_status, route_last30days
from agentie.core.skill_registry import all_skills


class Last30DaysSkillRegressionTests(unittest.TestCase):
    def test_skill_is_registered_as_real_external_runtime(self):
        skill=all_skills()['last30days']
        self.assertEqual(skill.get('kind'),'external')
        self.assertEqual(skill.get('repository'),LAST30_REPO)
        self.assertIn('recent_research',skill.get('capabilities',[]))
        self.assertIn('runtime',skill)

    def test_status_never_claims_ready_without_engine_and_python312(self):
        status=last30days_status()
        if not LAST30_SCRIPT.exists():self.assertFalse(status['ready'])
        if status['ready']:
            self.assertTrue(status['installed']);self.assertIsNotNone(status['python'])

    def test_uninstalled_research_returns_installable_runtime_card(self):
        if LAST30_SCRIPT.exists():self.skipTest('Last30Days is installed on this test machine')
        result=route_last30days('last30days AI coding agents')
        self.assertEqual(result['card']['type'],'skill_runtime')
        self.assertEqual(result['card']['skill'],'last30days')
        self.assertIn('install',result['message'].lower())

    def test_upstream_repo_and_runtime_are_not_placeholder_links(self):
        text=Path('agentie/core/external_skill_runtime.py').read_text(encoding='utf-8')
        self.assertIn('git", "clone"',text)
        self.assertIn('last30days.py',text)
        self.assertIn('--emit=compact',text)
        self.assertIn('Python 3.12+',text)


if __name__=='__main__':unittest.main()
