import unittest
from pathlib import Path


class WSLComputerIntegrationRegressionTests(unittest.TestCase):
    def test_setup_script_exists_and_targets_current_computer_stack(self):
        script = Path("scripts/setup_wsl_computer.sh")
        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")
        self.assertIn("google-chrome", text)

    def test_windows_launcher_starts_wsl_before_agentie(self):
        script = Path("scripts/start_agentie_with_wsl_computer.ps1")
        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")
        self.assertIn("python main.py", text)

    def test_frontend_embeds_kasmvnc_real_computer(self):
        script = Path("frontend/browser_screen.js")
        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")
        self.assertIn("kasmvnc_url", text)
        self.assertIn("KasmVNC Linux desktop", text)
        self.assertIn("Agentie Computer", text)
        self.assertIn("arc-frame", text)
        self.assertIn("arc-minimize", text)
        self.assertIn("arc-maximize", text)
        self.assertIn("arc-close", text)


if __name__ == "__main__":
    unittest.main()