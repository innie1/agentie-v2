import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import agent_prompt, agent_registry
from agentie.core.npc_brain import try_npc_response


class AgentPromptNPCRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        self.old_agents=agent_registry.AGENTS_FILE;self.old_aw=agent_registry.WORKSPACE
        self.old_prompts=agent_prompt.PROMPTS_FILE;self.old_pw=agent_prompt.WORKSPACE
        agent_registry.WORKSPACE=root;agent_registry.AGENTS_FILE=root/'agents.json'
        agent_prompt.WORKSPACE=root;agent_prompt.PROMPTS_FILE=root/'agent_instruction_profiles.json'
        self.agent=agent_registry.create_agent('Alex','CTO',purpose='Lead product engineering',permissions={'delegate':True})["agent"]
    def tearDown(self):
        agent_registry.AGENTS_FILE=self.old_agents;agent_registry.WORKSPACE=self.old_aw
        agent_prompt.PROMPTS_FILE=self.old_prompts;agent_prompt.WORKSPACE=self.old_pw
        self.temp.cleanup()

    def test_agent_prompt_contains_identity_role_and_explicit_delegation_without_raw_purpose(self):
        text=agent_prompt.build_agent_instructions(self.agent)
        self.assertIn('You are Alex',text);self.assertIn('Role: CTO',text)
        self.assertNotIn('Primary purpose:',text);self.assertNotIn('Lead product engineering',text)
        self.assertIn('may delegate bounded work',text.lower())
        same_title=agent_registry.create_agent('Other CTO','CTO',purpose='Lead another product')["agent"]
        other_text=agent_prompt.build_agent_instructions(same_title)
        self.assertNotIn('may delegate bounded work',other_text.lower())

    def test_concise_default_and_detailed_reports_can_coexist(self):
        agent_prompt.learn_from_user_message(self.agent,'I prefer short concise replies.')
        agent_prompt.learn_from_user_message(self.agent,'For reports I want detailed comprehensive reports.')
        text=agent_prompt.build_agent_instructions(self.agent)
        self.assertIn('conversational replies should be concise',text)
        self.assertIn('Reports, research and analysis',text)
        self.assertIn('detailed when needed',text)

    def test_learning_does_not_copy_full_chat(self):
        message='I prefer short concise replies because this sentence contains a lot of temporary discussion that should not become the prompt.'
        agent_prompt.learn_from_user_message(self.agent,message)
        raw=agent_prompt.PROMPTS_FILE.read_text(encoding='utf-8')
        self.assertNotIn('temporary discussion',raw)
        self.assertIn('default_length',raw)

    def test_npc_brain_learns_preference_without_provider(self):
        result=try_npc_response(self.agent,'From now on keep implementation commands easy to copy and paste')
        self.assertIsNotNone(result);self.assertEqual(result.get('routed_by'),'npc_brain')
        text=agent_prompt.build_agent_instructions(self.agent)
        self.assertIn('easy to copy and paste',text.lower())

    def test_delete_agent_purges_instruction_profile(self):
        agent_prompt.learn_from_user_message(self.agent,'I prefer short concise replies.')
        self.assertIn(self.agent['id'],json.loads(agent_prompt.PROMPTS_FILE.read_text(encoding='utf-8'))['agents'])
        with patch('agentie.core.memory_store.purge_agent_memory',return_value={'memories':0,'messages':0,'semantic_items':0}):
            result=agent_registry.delete_agent(self.agent['id'])
        data=json.loads(agent_prompt.PROMPTS_FILE.read_text(encoding='utf-8'))
        self.assertNotIn(self.agent['id'],data.get('agents',{}));self.assertEqual(result['purged']['instruction_profiles'],1)

    def test_runner_injects_npc_before_provider_and_assistant_accepts_prompt(self):
        runner=Path('agentie/core/runner.py').read_text(encoding='utf-8');assistant=Path('agentie/agents/assistant.py').read_text(encoding='utf-8')
        self.assertIn('try_npc_response',runner);self.assertIn('persistent_instructions',runner)
        self.assertLess(runner.index('try_npc_response'),runner.index('get_provider_info()'))
        self.assertIn('def build_assistant',assistant)
        self.assertIn('persistent_instructions',assistant)
        self.assertIn('persistent_agent',assistant)
        self.assertIn('Persistent identity, goals, responsibilities and user preferences',assistant)
        self.assertIn('workspace, not to one individual agent',assistant)
        self.assertIn('tools_for_persistent_agent(persistent_agent)',assistant)


if __name__=='__main__':unittest.main()
