import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import desktop_runtime


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

    def test_natural_app_commands_route_to_desktop(self):
        cases = {
            "Open the terminal": "terminal",
            "Open file manager": "files",
            "Open computer notes": "notes",
            "Open computer tasks": "tasks",
            "Show desktop": "home",
        }
        for text, app in cases.items():
            with self.subTest(text=text):
                result = desktop_runtime.route_desktop_request(text)
                self.assertIsNotNone(result)
                self.assertEqual(result["card"]["type"], "desktop_view")
                self.assertEqual(result["card"]["app"], app)

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


if __name__ == "__main__":
    unittest.main()
