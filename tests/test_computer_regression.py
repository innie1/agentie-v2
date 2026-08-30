import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import desktop_runtime
from agentie.core.browser_monitor import route_browser_request
from agentie.core.mcp_catalog import preset_by_id, presets
from agentie.core.mcp_client import _split_local_command


READY = {
    "computer_id": "company-default",
    "state": "USER_CONTROL",
    "running": True,
    "display_ready": True,
    "browser_ready": True,
    "display_url": "http://127.0.0.1:6088/vnc.html?autoconnect=1",
    "controller_type": "user",
    "controller_agent_id": None,
    "disk_exists": True,
    "acceleration": {"available": True, "accelerator": "whpx"},
    "profile": {"vm_ram_mb": 1024, "vm_vcpus": 1},
}
STOPPED = {
    **READY,
    "state": "STOPPED",
    "running": False,
    "display_ready": False,
    "browser_ready": False,
    "display_url": None,
    "controller_type": None,
}


class ComputerRoutingRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        self.workspace.joinpath("hello.txt").write_text("hello computer", encoding="utf-8")
        self.patch = patch.object(desktop_runtime, "WORKSPACE", self.workspace)
        self.patch.start()

    async def asyncTearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    async def test_desktop_requests_are_wired_into_main_computer_route(self):
        result = await route_browser_request("Open file manager")
        self.assertIsNotNone(result)
        self.assertEqual(result["card"]["type"], "desktop_view")
        self.assertEqual(result["card"]["app"], "files")
        self.assertIn("hello.txt", {item["name"] for item in result["card"]["items"]})

    async def test_native_task_phrase_is_not_stolen_by_desktop(self):
        result = await route_browser_request("Show my tasks")
        self.assertIsNone(result)

    async def test_show_desktop_routes_to_qemu_company_computer(self):
        with patch.object(desktop_runtime, "start_computer", return_value=READY) as start, patch.object(desktop_runtime, "ensure_guest_runtime", return_value=READY) as prepare, patch.object(desktop_runtime, "acquire_user", return_value=READY) as acquire:
            result = await route_browser_request("Show desktop")
        start.assert_called_once()
        prepare.assert_not_called()
        acquire.assert_called_once()
        self.assertEqual(result["card"]["mode"], "qemu")
        self.assertEqual(result["card"]["computer_id"], "company-default")
        self.assertTrue(result["card"]["running"])

    async def test_terminal_routes_through_same_qemu_company_computer(self):
        with patch.object(desktop_runtime, "start_computer", return_value=READY) as start, patch.object(desktop_runtime, "ensure_guest_runtime", return_value=READY) as prepare, patch.object(desktop_runtime, "acquire_user", return_value=READY) as acquire:
            result = await route_browser_request("Open the terminal")
        start.assert_called_once()
        prepare.assert_called_once()
        acquire.assert_called_once()
        self.assertEqual(result["card"]["mode"], "qemu")
        self.assertEqual(result["card"]["computer_id"], "company-default")

    async def test_stop_routes_to_qemu_shutdown(self):
        with patch.object(desktop_runtime, "stop_computer", return_value=STOPPED) as shutdown:
            result = await route_browser_request("Desktop control: stop")
        shutdown.assert_called_once()
        self.assertEqual(result["card"]["mode"], "qemu")
        self.assertEqual(result["card"]["app"], "stopped")
        self.assertFalse(result["card"]["running"])

    async def test_no_wsl_compatibility_hooks_remain_in_desktop_runtime(self):
        source = Path("agentie/core/desktop_runtime.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("ensure_wsl_desktop", source)
        self.assertNotIn("stop_wsl_desktop", source)
        self.assertNotIn('mode="wsl"', source)


class ComputerMCPPresetRegressionTests(unittest.TestCase):
    def test_required_computer_mcp_presets_exist(self):
        ids = {item["id"] for item in presets()}
        self.assertTrue({"filesystem", "playwright", "github", "agentmail", "memory", "sequential-thinking", "fetch", "time-mcp", "git"}.issubset(ids))

    def test_filesystem_is_workspace_scoped(self):
        item = preset_by_id("filesystem")
        self.assertIsNotNone(item)
        self.assertIn("server-filesystem", item["command"])
        self.assertIn("workspace", item["command"].lower())

    def test_github_wrapper_uses_allowed_python_launcher(self):
        item = preset_by_id("github")
        command, args = _split_local_command(item["command"])
        self.assertIn(Path(command).name.lower(), {"python", "python.exe", "py", "py.exe"})
        self.assertEqual(args[-2:], ["-m", "agentie.mcp_github_wrapper"])

    def test_agentmail_uses_official_stdio_bridge_and_requires_key(self):
        item = preset_by_id("agentmail")
        self.assertIsNotNone(item)
        self.assertIn("agentmail-mcp", item["command"])
        self.assertIn("AGENTMAIL_API_KEY", item["requires"])
        self.assertIn("send_message", item["sensitive_tools"])


if __name__ == "__main__":
    unittest.main()
