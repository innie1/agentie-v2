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

    def test_name_goes_directly_to_real_create_with_main_model_identity_and_no_agent_tool_grants(self):
        self.assertIn('async function createFromName', self.ui)
        self.assertIn("api('/agent-builder/draft'", self.ui)
        self.assertIn("api('/agent-builder/create'", self.ui)
        self.assertIn("IDENTITY_MARKER='[agentie:use-main-identity-model]'", self.ui)
        self.assertIn("skills:[],plugins:[],instructions:''", self.ui)
        self.assertNotIn('autoCapabilityIds', self.ui)
        self.assertIn('can_delegate:!!draft.can_delegate_recommended', self.ui)
        self.assertNotIn('renderReview', self.ui)
        self.assertNotIn('Recommended Skills', self.ui)
        self.assertNotIn('Recommended plugins / MCPs', self.ui)
        self.assertIn('Never invent a different job', self.builder)
        self.assertNotIn('Sales Agent', self.builder)
        self.assertNotIn('Research Agent', self.builder)

    def test_main_model_personality_runs_only_for_real_creator_marker(self):
        description='I need someone who helps organize product ideas.'
        with patch.object(agent_builder,'_main_model_personality',return_value='Methodical and curious, turning scattered ideas into clear priorities while questioning weak assumptions.') as generate:
            normal=agent_builder.draft_agent_spec(description,name='Mat')
            cloud=agent_builder.draft_agent_spec(description+'\n\n[agentie:use-main-identity-model]',name='Mat')
        self.assertEqual(normal['personality_source'],'fallback')
        self.assertEqual(cloud['personality_source'],'main_api')
        self.assertIn('Methodical and curious',cloud['working_style'])
        self.assertEqual(generate.call_count,1)
        self.assertNotIn('[agentie:',cloud['description'])

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

    def test_default_profile_hides_internal_counts_and_details(self):
        scope='.employee-profile-card:not(.employee-profile-form)'
        self.assertIn(f'{scope} .employee-profile-personality,{scope} .employee-profile-stats{{display:none!important}}', self.loader)
        self.assertIn(f'{scope} .employee-profile-section{{display:none!important}}', self.loader)
        self.assertIn(f'{scope} .employee-profile-section:first-child{{display:block!important', self.loader)
        self.assertIn(f'{scope} .employee-profile-section:first-child>strong{{display:none!important}}', self.loader)
        self.assertIn('background:linear-gradient', self.loader)
        self.assertNotIn('radial-gradient', self.loader)

    def test_profile_details_are_unified_and_delete_uses_existing_approval_command(self):
        self.assertIn("edit.textContent='Edit details'",self.loader)
        self.assertIn("btn.textContent.trim()==='Instructions'",self.loader)
        self.assertIn("label.textContent='Instructions'",self.loader)
        self.assertIn("button.textContent='Delete agent'",self.loader)
        self.assertIn("runProfile(`Delete agent ${agent.id}`",self.loader)
        self.assertIn("window.addAssistant(data.message",self.loader)
        self.assertNotIn('Generated system instructions',self.loader)
        self.assertNotIn('Learned preferences',self.loader)

    def test_shared_tool_catalog_blocks_old_per_agent_access_editor(self):
        self.assertIn('Shared workspace tools',self.loader)
        self.assertIn('agentie-shared-access-sentinel',self.loader)
        self.assertIn('.agent-access-box:not(.agentie-shared-access-sentinel)',self.loader)
        self.assertIn('available to every agent automatically',self.loader)

    def test_group_and_skill_items_reuse_existing_creators(self):
        self.assertIn("document.querySelector('.n4-chats')", self.ui)
        self.assertIn("x.textContent.trim()==='New group chat'", self.ui)
        self.assertIn("document.querySelector('.platform-skill-new')", self.ui)
        self.assertNotIn('/agent-threads', self.ui)
        self.assertNotIn('/workflow-skills', self.ui)

    def test_product_ideas_request_becomes_clean_visible_identity(self):
        description='I need someone who helps organize product ideas.'
        with (
            patch.object(agent_builder, 'recommend_skills', return_value=[]),
            patch.object(agent_builder, 'recommend_plugins', return_value=[]),
            patch.object(agent_builder, 'recommend_manager', return_value=None),
            patch.object(agent_builder, 'recommend_collaborators', return_value=[]),
            patch.object(agent_builder, 'routine_suggestions', return_value=[]),
            patch.object(agent_builder, 'capability_gaps', return_value=[]),
        ):
            draft=agent_builder.draft_agent_spec(description, name='Mat')
        self.assertEqual(draft['name'], 'Mat')
        self.assertEqual(draft['job'], 'Product Ideas')
        self.assertEqual(draft['description'], description)
        self.assertNotIn('I need someone', draft['job'])
        self.assertNotIn('described by the user', draft['goal'])
        self.assertIn('product ideas', draft['goal'].lower())
        self.assertEqual(len(draft['responsibilities']), 3)
        self.assertIn('Organize product ideas', draft['responsibilities'][0])

    def test_unusual_custom_job_gets_a_concise_title_without_fixed_profession(self):
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
        self.assertEqual(draft['job'], 'Greenhouse Temperature')
        self.assertEqual(draft['description'], description)
        self.assertNotEqual(draft['job'], description.rstrip('.'))
        self.assertEqual(draft['runtime_profile'], 'general')
        self.assertNotIn('Sales Agent', draft['job'])
        self.assertNotIn('Research Agent', draft['job'])

    def test_task_verbs_still_recommend_relevant_skills_for_discovery_not_grants(self):
        skills=[
            {'id':'planning','name':'Planning & Reasoning','description':'Planning and verification','capabilities':['planning'],'enabled':True,'kind':'capability'},
            {'id':'knowledge-memory','name':'Knowledge Memory','description':'Long-term knowledge','capabilities':['memory'],'enabled':True,'kind':'capability'},
            {'id':'research','name':'Research','description':'Web research','capabilities':['web_search'],'enabled':True,'kind':'capability'},
        ]
        with patch.object(agent_builder, 'list_skills', return_value=skills):
            recommended=agent_builder.recommend_skills('I need someone who helps organize product ideas.')
        ids=[item['id'] for item in recommended]
        self.assertIn('planning', ids)
        self.assertIn('knowledge-memory', ids)
        self.assertNotIn('research', ids)


if __name__ == '__main__':
    unittest.main()
