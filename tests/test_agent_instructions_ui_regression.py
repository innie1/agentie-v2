import unittest
from pathlib import Path

class AgentInstructionsUIRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.legacy=Path('frontend/plugins.js').read_text(encoding='utf-8')
        cls.loader=Path('frontend/create_menu_loader.js').read_text(encoding='utf-8')
        cls.prompt=Path('agentie/core/agent_prompt.py').read_text(encoding='utf-8')
    def test_profile_uses_one_edit_details_entry_instead_of_separate_instructions_button(self):
        self.assertIn("edit.textContent='Edit details'",self.loader)
        self.assertIn("btn.textContent.trim()==='Instructions'",self.loader)
        self.assertIn('btn.remove()',self.loader)
    def test_details_editor_contains_identity_and_user_instructions_in_one_form(self):
        self.assertIn("label.textContent='Instructions'",self.loader)
        self.assertIn("heading.textContent=`${agent.name} · Details`",self.loader)
        self.assertIn('Identity, role and durable working instructions.',self.loader)
        self.assertIn("save.textContent='Save details'",self.loader)
    def test_long_generated_prompt_is_internal_not_rendered_in_unified_profile(self):
        self.assertNotIn('Generated system instructions',self.loader)
        self.assertNotIn('Learned preferences',self.loader)
        self.assertIn('generated_prompt',self.prompt)
        self.assertIn('build_agent_instructions',self.prompt)
    def test_profile_has_real_delete_button_using_existing_agent_delete_approval_route(self):
        self.assertIn("button.textContent='Delete agent'",self.loader)
        self.assertIn("runProfile(`Delete agent ${agent.id}`",self.loader)
        role=Path('agentie/core/role_store.py').read_text(encoding='utf-8')
        self.assertIn('action=f"delete_agent:{target[\'id\']}"',role)
        self.assertIn('create_approval(action',role)
    def test_legacy_instruction_implementation_can_remain_for_compatibility_but_is_not_profile_default(self):
        self.assertIn('View / edit instructions',self.legacy)
        self.assertIn('Generated system prompt',self.legacy)
        self.assertIn("btn.textContent.trim()==='Instructions'",self.loader)

if __name__=='__main__':unittest.main()
