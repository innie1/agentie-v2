import unittest
from pathlib import Path


class WSLComputerIntegrationRegressionTests(unittest.TestCase):
    def test_setup_script_exists_and_starts_novnc(self):
        script = Path("scripts/setup_wsl_computer.sh")
        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")
        self.assertIn("tigervnc-standalone-server", text)
        self.assertIn("websockify", text)
        self.assertIn("127.0.0.1:6080", text)
        self.assertIn("google-chrome", text)

    def test_windows_launcher_starts_wsl_before_agentie(self):
        script = Path("scripts/start_agentie_with_wsl_computer.ps1")
        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")
        self.assertIn("~/.agentie-computer/start.sh", text)
        self.assertIn("AGENTIE_COMPUTER_URL", text)
        self.assertIn("python main.py", text)

    def test_frontend_embeds_novnc_real_computer(self):
        script = Path("frontend/browser_screen.js")
        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")
        self.assertIn("vnc.html", text)
        self.assertIn("127.0.0.1:6080", text)
        self.assertIn("Agentie real computer", text)


if __name__ == "__main__":
    unittest.main()
