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
        self.assertIn("showOverlay('Starting Computer'", self.text)

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
        self.assertIn("Starting Computer", self.text)

    def test_close_dismisses_the_view_without_waiting_for_shutdown(self):
        self.assertIn("function dismissComputer()", self.text)
        self.assertIn(".arc-close').onclick=dismissComputer", self.text)
        self.assertIn("row.remove()", self.text)

    def test_stuck_starting_overlay_retries_the_real_desktop_connection(self):
        self.assertIn("readyRetry=setTimeout", self.text)
        self.assertIn("ensureComputer(true)", self.text)
        self.assertIn("currentComputerState==='STARTING'", self.text)

    def test_hypervisor_display_and_human_takeover_are_native(self):
        self.assertIn("==='qemu'", self.text)
        self.assertIn("card.display_url", self.text)
        self.assertIn("computer_takeover", self.text)
        self.assertIn("Take Control", self.text)
        self.assertIn("Continue Agent", self.text)
        self.assertIn("Desktop control: take user control", self.text)
        self.assertIn("Desktop control: continue agent", self.text)

    def test_old_computer_terminology_is_removed(self):
        low=self.text.lower()
        self.assertNotIn("kasmvnc",low)
        self.assertNotIn("mode==='wsl'",low)
        self.assertNotIn("wsl desktop",low)
        self.assertNotIn("xfce",low)


if __name__ == "__main__":
    unittest.main()
