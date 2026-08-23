import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import agent_builder


class CreateMenuAgentOnboardingRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = Path('frontend/create_menu.js').read_text(encoding='utf-8')
        cls.loader = Path('frontend/create_menu_loader.js').read_text(encoding='utf-8')
        cls.api = Path('agentie/core/platform_next4_api.py').read_text(encoding='utf-8')
        cls.builder = Path('agentie/core/agent_builder.py').read_text(encoding='utf-8')

    def test_plus_menu_has_exact_three_creation_choices(self):
        for marker in (
            "['Create an Agent',startAgentOnboarding]",
            "['Create a Group Chat',openExistingGroupCreator]",
            "['Create a Skill',openExistingSkillCreator]",
        ):
            self.assertIn(marker, self.ui)

    def test_agent_creation_is_chat_native_with_four_generic_choices_and_free_text(self):
        for marker in (
            'Hey, I want to join the team 👋',
            'What would you like me to help with?',
            'What should I help with first?',
            'Research & find information',
            'Create, write or build things',
            'Organize, manage or monitor work',
            'Use tools and automate tasks',
            "own.placeholder='Type your own answer'",
            "list.className='agentie-choice-list'",
        ):
            self.assertIn(marker, self.ui)

    def test_normal_composer_stays_visible_and_can_answer_onboarding(self):
        self.assertNotIn('visibility:hidden', self.ui)
        self.assertNotIn('pointer-events:none', self.ui)
        self.assertIn("event.target.closest?.('#sendButton')", self.ui)
        self.assertIn("event.target!==composerInput()", self.ui)
        self.assertIn("setComposerPlaceholder('Describe what you want this agent to do…')", self.ui)
        self.assertIn("setComposerPlaceholder('Type my name…')", self.ui)

    def test_name_question_and_default_new_agentie_are_exact(self):
        self.assertIn("const DEFAULT_NAME='New Agentie'", self.ui)
        self.assertIn('assistant("What\'s my name?")', self.ui)
        self.assertIn("String(rawName||'').trim()||DEFAULT_NAME", self.ui)
        self.assertIn("fallback.textContent='Use New Agentie'", self.ui)

    def test_name_goes_directly_to_real_create_without_visible_technical_review(self):
        self.assertIn('async function createFromName', self.ui)
        self.assertIn("api('/agent-builder/draft'", self.ui)
        self.assertIn("api('/agent-builder/create'", self.ui)
        self.assertIn("skills:autoCapabilityIds(draft,'skill')", self.ui)
        self.assertIn("plugins:autoCapabilityIds(draft,'plugin')", self.ui)
        self.assertIn("kind==='skill'||!!item.installed", self.ui)
        self.assertIn('can_delegate:!!draft.can_delegate_recommended', self.ui)
        self.assertNotIn('renderReview', self.ui)
        self.assertNotIn('Recommended Skills', self.ui)
        self.assertNotIn('Recommended plugins / MCPs', self.ui)
        self.assertIn('Do not assume a predefined profession or department', self.builder)

    def test_new_agent_opens_with_natural_welcome_not_job_description(self):
        self.assertIn("welcome.textContent.trim().startsWith('Chatting with ')", self.ui)
        self.assertIn("welcome.textContent='Want to put me on a task?'", self.ui)
        self.assertIn("window.addAssistant('Want to put me on a task?',null)", self.ui)
        self.assertNotIn("What should we work on first?", self.ui)

    def test_creation_ui_is_lazy_loaded_to_protect_startup(self):
        bundle='_frontend_bundle("platform_next4.js", "platform_chat_focus_guard.js", "group_chat_markdown.js", "model_router.js", "group_chat_offline_cache.js", "navigation_connect.js", "group_chat_instant_open.js", "create_menu_loader.js")'
        self.assertIn(bundle, self.api)
        self.assertNotIn('"group_chat_instant_open.js", "create_menu.js")', self.api)
        self.assertIn("script.src='/platform-create-menu.js?v=2'", self.loader)
        self.assertIn("event.target.closest?.('.agent-create')", self.loader)
        self.assertIn('event.stopImmediatePropagation()', self.loader)
        self.assertIn('@router.get("/platform-create-menu.js")', self.api)
        self.assertIn('@router.get("/platform-create-menu-loader.js")', self.api)

    def test_choice_list_visual_language_is_shared_with_existing_choosers(self):
        self.assertIn('.agentie-choice-list,.platform-options,.n4-agent-picks', self.loader)
        self.assertIn('.agentie-choice-row,.platform-option,.n4-agent-pick', self.loader)
        self.assertIn('accent-color:#0b84ff', self.loader)

    def test_group_and_skill_items_reuse_existing_creators(self):
        self.assertIn("document.querySelector('.n4-chats')", self.ui)
        self.assertIn("x.textContent.trim()==='New group chat'", self.ui)
        self.assertIn("document.querySelector('.platform-skill-new')", self.ui)
        self.assertNotIn('/agent-threads', self.ui)
        self.assertNotIn('/workflow-skills', self.ui)

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
