import unittest
from pathlib import Path


class AgentChoiceUIRegressionTests(unittest.TestCase):
    def test_missing_agent_choice_is_interactive_and_reuses_agentie_action_style(self):
        text=Path("frontend/cards.js").read_text(encoding="utf-8")
        self.assertIn("agent_choice:renderAgentChoice",text)
        self.assertIn("addTitle(el,'Choose an agent')",text)
        self.assertIn("className='browser-approval-step'",text)
        self.assertIn("className='browser-approval-actions'",text)
        self.assertIn("if(index===0)b.className='approve'",text)
        self.assertIn("option.action==='create_agent'",text)
        self.assertIn("continuationCommand(c,chosen)",text)
        self.assertIn("Give it to",Path("agentie/core/team_orchestrator.py").read_text(encoding="utf-8"))


if __name__=="__main__":unittest.main()
