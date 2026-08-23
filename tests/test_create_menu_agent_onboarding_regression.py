import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import agent_builder


class CreateMenuAgentOnboardingRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = Path('frontend/create_menu.js').read_text(encoding='utf-8')
        cls.api = Path('agentie/core/platform_next4_api.py').read_text(encoding='utf-8')
        cls.builder = Path('agentie/core/agent_builder.py').read_text(encoding='utf-8')

    def test_plus_menu_has_exact_three_creation_choices_and_owns_click_first(self):
        src = self.ui
        for marker in (
            "['Create an Agent',startAgentOnboarding]",
            "['Create a Group Chat',openExistingGroupCreator]",
            "['Create a Skill',openExistingSkillCreator]",
            "window.addEventListener('click'",
            "event.target.closest?.('.agent-create')",
            "event.stopImmediatePropagation()",
        ):
            self.assertIn(marker, src)
        self.assertIn('},true);', src)

    def test_agent_creation_is_chat_native_with_four_generic_starters_and_free_text(self):
        src = self.ui
        for marker in (
            'Hey, I want to join the team 👋',
            'What would you like me to help with?',
            'Research & find information',
            'Create, write or build things',
            'Organize, manage or monitor work',
            'Use tools and automate tasks',
            "custom.placeholder='Or describe any Bot you need...'",
            'data-create-starter',
            "choose.dataset.createStep='purpose'",
            'They do not lock the Bot into a profession or agent type.',
        ):
            self.assertIn(marker, src)

    def test_name_question_and_default_new_agentie_are_exact(self):
        src = self.ui
        self.assertIn("const DEFAULT_NAME='New Agentie'", src)
        self.assertIn('assistant("What\'s my name?")', src)
        self.assertIn("String(name||'').trim()||DEFAULT_NAME", src)
        self.assertIn("label:'Use New Agentie'", src)

    def test_agent_onboarding_reuses_real_builder_and_only_checked_capabilities(self):
        src = self.ui
        self.assertIn("api('/agent-builder/draft'", src)
        self.assertIn("api('/agent-builder/create'", src)
        self.assertIn("[data-create-capability]:checked", src)
        self.assertIn("if(kind==='plugin'&&!item.installed)check.disabled=true", src)
        self.assertIn('plugins:selected.filter', src)
        self.assertIn('skills:selected.filter', src)
        self.assertIn('Do not assume a predefined profession or department', self.builder)
        self.assertIn('runtime_profile":"general"', self.builder)

    def test_group_and_skill_items_reuse_existing_creators(self):
        src = self.ui
        self.assertIn("document.querySelector('.n4-chats')", src)
        self.assertIn("x.textContent.trim()==='New group chat'", src)
        self.assertIn("document.querySelector('.platform-skill-new')", src)
        self.assertNotIn('/agent-threads', src)
        self.assertNotIn('/workflow-skills', src)

    def test_create_menu_loads_last_after_group_runtime(self):
        bundle='_frontend_bundle("platform_next4.js", "platform_chat_focus_guard.js", "group_chat_markdown.js", "model_router.js", "group_chat_offline_cache.js", "navigation_connect.js", "group_chat_instant_open.js", "create_menu.js")'
        self.assertIn(bundle, self.api)
        self.assertLess(bundle.index('navigation_connect.js'), bundle.index('group_chat_instant_open.js'))
        self.assertLess(bundle.index('group_chat_instant_open.js'), bundle.index('create_menu.js'))
        self.assertIn('@router.get("/platform-create-menu.js")', self.api)

    def test_unusual_custom_job_stays_user_defined_not_a_fixed_profession(self):
        description='Track greenhouse temperature readings and keep a daily change log.'
        with (
            patch.object(agent_builder, 'recommend_skills', return_value=[]),
            patch.object(agent_builder, 'recommend_plugins', return_value=[]),
            patch.object(agent_builder, 'recommend_manager', return_value=None),
            patch.object(agent_builder, 'recommend_collaborators', return_value=[]),
            patch.object(agent_builder, 'routine_suggestions', return_value=[]),
            patch.object(agent_builder, 'capability_gaps', return_value=[]),
        ):
            draft=agent_builder.draft_agent_spec(description, name='Greenhouse')
        self.assertEqual(draft['name'], 'Greenhouse')
        self.assertEqual(draft['job'], description.rstrip('.'))
        self.assertEqual(draft['runtime_profile'], 'general')
        self.assertIn('Do not assume a predefined profession or department', draft['instructions'])
        self.assertNotIn('Sales Agent', draft['job'])
        self.assertNotIn('Research Agent', draft['job'])


if __name__ == '__main__':
    unittest.main()
