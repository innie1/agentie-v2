import unittest
from pathlib import Path


class InlineComputerCardRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = Path("frontend/browser_screen.js").read_text(encoding="utf-8")

    def test_computer_is_mini_chat_card(self):
        self.assertIn("width:min(500px,84vw)", self.text)
        self.assertIn("aspect-ratio:16/9", self.text)

    def test_use_computer_fallback_is_detected_before_response(self):
        self.assertIn("use\\s+computer\\s+for", self.text)
        self.assertIn("setTimeout(()=>{place();setState('starting','');showOverlay('Starting','')", self.text)

    def test_computer_is_anchored_after_latest_user_message(self):
        self.assertIn("messages.querySelectorAll('.user-row')", self.text)
        self.assertIn("anchor.after(row)", self.text)

    def test_computer_calls_stay_in_active_agent_session(self):
        self.assertIn("const a=activeAgent()", self.text)
        self.assertIn("session_id:`${a.session_prefix}main`", self.text)
        self.assertIn("ownerKey=agentKey()", self.text)

    def test_computer_title_uses_active_agent_name(self):
        self.assertIn("function computerOwnerName()", self.text)
        self.assertIn("title.textContent=`${computerOwnerName()} Computer`", self.text)
        self.assertIn("Starting computer", self.text)
        self.assertNotIn("Waiting for Agentie computer route", self.text)


if __name__ == "__main__":
    unittest.main()
