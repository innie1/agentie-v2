import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from agentie.core import agent_prompt
from agentie.core.npc_brain import try_npc_response

class AgentInstructionEditRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=agent_prompt.PROMPTS_FILE;agent_prompt.PROMPTS_FILE=Path(self.temp.name)/'profiles.json';self.agent={'id':'agt_test','name':'Alex','role':'CTO','base':'manager','purpose':'Lead engineering','permissions':{'delegate':True},'skills':[]}
    def tearDown(self):agent_prompt.PROMPTS_FILE=self.old;self.temp.cleanup()
    def test_manual_instructions_are_stored_separately_from_learned_preferences(self):
        agent_prompt.learn_from_user_message(self.agent,'I prefer short concise replies')
        agent_prompt.set_manual_instructions(self.agent,'Always protect backwards compatibility.')
        p=agent_prompt.get_instruction_profile(self.agent);self.assertEqual(p['manual_instructions'],'Always protect backwards compatibility.');self.assertEqual(p['communication']['default_length'],'concise')
    def test_manual_instructions_have_explicit_priority_in_generated_prompt(self):
        agent_prompt.set_manual_instructions(self.agent,'Always protect backwards compatibility.')
        text=agent_prompt.build_agent_instructions(self.agent);self.assertIn('USER-EDITED AGENT INSTRUCTIONS',text);self.assertIn('outrank automatically learned preferences',text)
    def test_instruction_card_exposes_generated_and_editable_sections(self):
        card=agent_prompt.instruction_card(self.agent);self.assertEqual(card['type'],'agent_instructions');self.assertIn('generated_prompt',card);self.assertIn('manual_instructions',card);self.assertIn('learned',card)
    def test_npc_reads_agent_profile_without_title_granting_hidden_runtime_class(self):
        agent_prompt.set_manual_instructions(self.agent,'Keep replies concise.')
        with patch('agentie.core.npc_brain.learn_from_user_message',return_value=[]):r=try_npc_response(self.agent,'What is your role?')
        # The configured CTO title remains identity, while explicit delegation
        # permission—not the title or legacy base field—selects planning behavior.
        self.assertEqual(r['npc_role'],'planning');self.assertEqual(r['routed_by'],'npc_brain');self.assertIn('CTO',r['message'])
        no_delegate={**self.agent,'id':'agt_test_2','permissions':{'delegate':False},'skills':[]}
        with patch('agentie.core.npc_brain.learn_from_user_message',return_value=[]):plain=try_npc_response(no_delegate,'Give me a debug checklist')
        self.assertIsNone(plain)
    def test_role_router_has_view_and_edit_instruction_commands(self):
        text=Path('agentie/core/role_store.py').read_text(encoding='utf-8');self.assertIn('instruction_card',text);self.assertIn('set_manual_instructions',text);self.assertIn('system\\s+prompt|instructions|prompt',text)

if __name__=='__main__':unittest.main()
