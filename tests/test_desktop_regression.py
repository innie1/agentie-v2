import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import desktop_runtime

READY = {
    "computer_id": "company-default",
    "state": "USER_CONTROL",
    "running": True,
    "display_ready": True,
    "browser_ready": True,
    "display_url": "http://127.0.0.1:6088/vnc.html?view_only=0",
    "controller_type": "user",
    "controller_agent_id": None,
    "disk_exists": True,
    "acceleration": {"available": True, "accelerator": "whpx"},
    "profile": {"vm_ram_mb": 1024, "vm_vcpus": 1},
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

    def test_show_desktop_starts_prepares_shared_qemu_computer_and_gives_user_control(self):
        with patch.object(desktop_runtime, "start_computer", return_value=READY) as start, patch.object(desktop_runtime, "ensure_guest_runtime", return_value=READY) as prepare, patch.object(desktop_runtime, "acquire_user", return_value=READY) as acquire:
            result = desktop_runtime.route_desktop_request("Show desktop")
        start.assert_called_once()
        prepare.assert_not_called()
        acquire.assert_called_once()
        self.assertEqual(result["card"]["mode"], "qemu")
        self.assertEqual(result["card"]["computer_id"], "company-default")
        self.assertEqual(result["card"]["state"], "USER_CONTROL")
        self.assertIn("6088", result["card"]["display_url"])

    def test_takeover_and_continue_agent_use_same_computer(self):
        user = {**READY, "state": "USER_CONTROL", "controller_type": "user"}
        agent = {**READY, "state": "AGENT_CONTROL", "controller_type": "agent", "controller_agent_id": "agt_sales"}
        with patch.object(desktop_runtime, "ensure_guest_runtime", return_value=READY), patch.object(desktop_runtime, "acquire_user", return_value=user):
            takeover = desktop_runtime.route_desktop_request("Desktop control: take user control")
        with patch.object(desktop_runtime, "continue_agent", return_value=agent):
            continued = desktop_runtime.route_desktop_request("Desktop control: continue agent")
        self.assertEqual(takeover["card"]["state"], "USER_CONTROL")
        self.assertEqual(continued["card"]["state"], "AGENT_CONTROL")
        self.assertEqual(takeover["card"]["computer_id"], continued["card"]["computer_id"])

    def test_open_terminal_opens_real_company_computer(self):
        with patch.object(desktop_runtime, "start_computer", return_value=READY), patch.object(desktop_runtime, "ensure_guest_runtime", return_value=READY) as prepare, patch.object(desktop_runtime, "acquire_user", return_value=READY):
            result = desktop_runtime.route_desktop_request("Open the terminal")
        prepare.assert_called_once()
        self.assertEqual(result["card"]["mode"], "qemu")
        self.assertTrue(result["card"]["persistent"])

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

    def test_host_terminal_rejects_arbitrary_shell(self):
        result = desktop_runtime.route_desktop_request("Desktop control: terminal powershell whoami")
        self.assertEqual(result["card"]["app"], "error")
        self.assertIn("not enabled", result["message"].lower())

    def test_actionable_virtualization_error_is_exposed(self):
        error_info = {**READY, "state": "ERROR", "running": False, "last_error": "WHPX is unavailable.", "acceleration": {"available": False, "accelerator": "whpx", "action": "Enable Windows Hypervisor Platform."}}
        with patch.object(desktop_runtime, "start_computer", side_effect=desktop_runtime.ComputerError("WHPX is unavailable. Enable Windows Hypervisor Platform.")), patch.object(desktop_runtime, "computer_status", return_value=error_info):
            result = desktop_runtime.route_desktop_request("Show desktop")
        self.assertEqual(result["card"]["mode"], "qemu")
        self.assertIn("Hypervisor", result["card"]["action"])


if __name__ == "__main__":
    unittest.main()
