import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agentie.core import desktop_runtime
from agentie.core.browser_monitor import route_browser_request
from agentie.core.mcp_catalog import preset_by_id, presets
from agentie.core.mcp_client import _split_local_command


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
        result = await route_browser_request("Show my files")
        self.assertIsNotNone(result)
        self.assertEqual(result["card"]["type"], "desktop_view")
        self.assertEqual(result["card"]["app"], "files")
        self.assertIn("hello.txt", {item["name"] for item in result["card"]["items"]})

    async def test_terminal_routes_through_same_computer_route(self):
        result = await route_browser_request("Open the terminal")
        self.assertEqual(result["card"]["app"], "terminal")

    async def test_stop_routes_to_full_computer_shutdown(self):
        fake = {"message": "Agentie Computer stopped.", "card": {"type": "desktop_view", "app": "stopped"}}
        with patch("agentie.core.computer_session.shutdown_computer", new=AsyncMock(return_value=fake)) as shutdown:
            result = await route_browser_request("Desktop control: stop")
        shutdown.assert_awaited_once()
        self.assertEqual(result["card"]["app"], "stopped")


class ComputerMCPPresetRegressionTests(unittest.TestCase):
    def test_required_computer_mcp_presets_exist(self):
        ids = {item["id"] for item in presets()}
        self.assertTrue({"filesystem", "playwright", "github", "memory", "sequential-thinking", "fetch", "time-mcp", "git"}.issubset(ids))

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


if __name__ == "__main__":
    unittest.main()
