import unittest
from pathlib import Path

class AgentInstructionsUIRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.text=Path('frontend/plugins.js').read_text(encoding='utf-8')
    def test_agent_menu_exposes_instruction_editor(self):
        self.assertIn('View / edit instructions',self.text);self.assertIn('Edit name & role',self.text);self.assertIn('Delete agent',self.text)
    def test_instruction_editor_separates_manual_learned_and_generated(self):
        self.assertIn('User instructions',self.text);self.assertIn('Learned preferences',self.text);self.assertIn('Generated system prompt',self.text)
    def test_generated_prompt_is_read_only(self):
        self.assertIn("gh.textContent='Read-only.",self.text);self.assertIn("gp.textContent=card.generated_prompt",self.text)
    def test_manual_instructions_can_be_saved(self):
        self.assertIn('Save instructions',self.text);self.assertIn('Set ${a.name} instructions to ${ta.value.trim()}',self.text)
    def test_ui_explains_conversation_learning(self):
        self.assertIn('Normal conversations can still teach this agent useful preferences over time.',self.text)
    def test_only_one_browser_menu_implementation_exists(self):
        section=self.text.split('// Single persistent-agent UI implementation.',1)[1]
        self.assertEqual(section.count('View / edit instructions'),1)
        self.assertEqual(section.count('menu.append(editItem,instructions,deleteItem)'),1)

if __name__=='__main__':unittest.main()
