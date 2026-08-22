import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import agent_registry, specialty_router, team_orchestrator
from agentie.core.agent_matching import task_signature


class SpecialtyDelegationRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        self.old_agents=agent_registry.AGENTS_FILE;self.old_aw=agent_registry.WORKSPACE
        self.old_team=team_orchestrator.TEAM_FILE;self.old_tw=team_orchestrator.WORKSPACE
        agent_registry.WORKSPACE=root;agent_registry.AGENTS_FILE=root/'agents.json'
        team_orchestrator.WORKSPACE=root;team_orchestrator.TEAM_FILE=root/'team_jobs.json'
        self.writer=agent_registry.create_agent('Writer','Content and social media owner',purpose='Write social media launch posts, blog posts and campaign copy',responsibilities=['Write social media posts','Draft launch and blog content'])["agent"]
        self.alex=agent_registry.create_agent('Alex','Engineering owner',purpose='Own technical architecture, software implementation and code',responsibilities=['Build software','Review technical architecture'])["agent"]
    def tearDown(self):
        agent_registry.AGENTS_FILE=self.old_agents;agent_registry.WORKSPACE=self.old_aw
        team_orchestrator.TEAM_FILE=self.old_team;team_orchestrator.WORKSPACE=self.old_tw
        self.temp.cleanup()

    def test_out_of_ownership_task_proposes_existing_best_match_before_starting(self):
        task='Write a social media launch post'
        with patch.object(specialty_router,'start_team_job') as start:
            result=specialty_router.maybe_auto_delegate(task,self.alex['session_prefix']+'main')
        self.assertIsNotNone(result);self.assertEqual(result['card']['type'],'agent_handoff_proposal')
        self.assertEqual(result['card']['from_agent']['name'],'Alex');self.assertEqual(result['card']['to_agent']['name'],'Writer')
        self.assertEqual(result['card']['specialty'],task_signature(task))
        labels=[action.get('label') for action in result['card']['actions']]
        self.assertIn('Accept',labels);self.assertIn('Always accept',labels)
        start.assert_not_called()

    def test_agent_keeps_work_that_matches_own_configured_ownership(self):
        result=specialty_router.maybe_auto_delegate('Write a blog post about our launch',self.writer['session_prefix']+'main')
        self.assertIsNone(result)

    def test_base_chat_never_auto_delegates(self):
        self.assertIsNone(specialty_router.maybe_auto_delegate('Write a launch post','ui:base'))

    def test_explicit_delegation_is_not_intercepted(self):
        self.assertIsNone(specialty_router.maybe_auto_delegate('Delegate write a launch post to Writer',self.alex['session_prefix']+'main'))

    def test_no_matching_agent_means_current_agent_keeps_task(self):
        agent_registry.delete_agent(self.writer['id'])
        self.assertIsNone(specialty_router.maybe_auto_delegate('Write a launch post',self.alex['session_prefix']+'main'))

    def test_specialty_router_is_local_and_has_no_predefined_profession_classes(self):
        text=Path('agentie/core/specialty_router.py').read_text(encoding='utf-8')
        self.assertNotIn('run_agent(',text);self.assertNotIn('provider',text.lower())
        self.assertNotIn('"writing"',text);self.assertNotIn('"research"',text);self.assertNotIn('"coding"',text)
        self.assertIn('best_agent(',text)


if __name__=='__main__':unittest.main()
