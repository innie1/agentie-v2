import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import desktop_runtime


READY = {
    "running": True,
    "novnc_ready": True,
    "chrome_ready": True,
    "novnc_url": "http://127.0.0.1:6080/vnc_lite.html?autoconnect=1",
    "distro": "Ubuntu",
    "message": "Agentie Computer started.",
}


class AgentieDesktopRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        self.workspace.joinpath("tasks.json").write_text('[{"title":"Build Agentie","status":"pending"}]', encoding="utf-8")
        self.workspace.joinpath("notes.json").write_text('[{"title":"Idea","content":"desktop"}]', encoding="utf-8")
        self.workspace.joinpath("hello.txt").write_text("hello desktop", encoding="utf-8")
        self.patch = patch.object(desktop_runtime, "WORKSPACE", self.workspace)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_show_desktop_starts_real_wsl_computer(self):
        with patch.object(desktop_runtime, "ensure_wsl_desktop", return_value=READY) as start:
            result = desktop_runtime.route_desktop_request("Show desktop")
        start.assert_called_once()
        self.assertEqual(result["card"]["type"], "desktop_view")
        self.assertEqual(result["card"]["mode"], "wsl")
        self.assertTrue(result["card"]["running"])
        self.assertIn("6080", result["card"]["novnc_url"])

    def test_open_terminal_starts_real_desktop(self):
        with patch.object(desktop_runtime, "ensure_wsl_desktop", return_value=READY):
            result = desktop_runtime.route_desktop_request("Open the terminal")
        self.assertEqual(result["card"]["mode"], "wsl")

    def test_existing_native_phrases_are_not_stolen(self):
        for text in ("Show my tasks", "Show my files", "Open my notes"):
            with self.subTest(text=text):
                self.assertIsNone(desktop_runtime.route_desktop_request(text))

    def test_files_app_uses_real_workspace(self):
        result = desktop_runtime.route_desktop_request("Desktop control: files")
        names = {item["name"] for item in result["card"]["items"]}
        self.assertIn("hello.txt", names)
        opened = desktop_runtime.route_desktop_request("Desktop control: open file hello.txt")
        self.assertEqual(opened["card"]["file"]["content"], "hello desktop")

    def test_terminal_supports_workspace_commands(self):
        result = desktop_runtime.route_desktop_request("Desktop control: terminal ls")
        self.assertEqual(result["card"]["app"], "terminal")
        self.assertIn("hello.txt", result["card"]["terminal"]["output"])

    def test_terminal_rejects_arbitrary_host_shell(self):
        result = desktop_runtime.route_desktop_request("Desktop control: terminal powershell whoami")
        self.assertEqual(result["card"]["app"], "error")
        self.assertIn("not enabled", result["message"].lower())

    def test_setup_required_is_exposed_in_card(self):
        info = {**READY, "running": False, "novnc_url": None, "setup_required": True, "setup_command": "sudo apt install novnc", "message": "One-time setup required."}
        with patch.object(desktop_runtime, "ensure_wsl_desktop", return_value=info):
            result = desktop_runtime.route_desktop_request("Show desktop")
        self.assertTrue(result["card"]["setup_required"])
        self.assertIn("sudo apt", result["card"]["setup_command"])


if __name__ == "__main__":
    unittest.main()
