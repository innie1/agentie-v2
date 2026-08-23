import asyncio
import unittest
from unittest.mock import patch

from agentie.core import browser_monitor


class CompanyComputerRoutingRegressionTests(unittest.TestCase):
    def test_browser_router_passes_active_agent_session_to_desktop_runtime(self):
        async def scenario():
            with patch("agentie.core.desktop_runtime.route_desktop_request", return_value={"message": "done", "card": {"type": "desktop_view", "mode": "qemu"}}) as desktop:
                result = await browser_monitor.route_browser_request("Run pwd in the terminal", "agent:agt_ops:main")
            desktop.assert_called_once_with("Run pwd in the terminal", "agent:agt_ops:main")
            return result
        result = asyncio.run(scenario())
        self.assertEqual(result["card"]["mode"], "qemu")

    def test_computer_fallback_keeps_active_session(self):
        async def scenario():
            with patch.object(browser_monitor, "_launch_computer_fallback", return_value={"message": "ready", "card": {"type": "desktop_view", "mode": "qemu"}}) as launch:
                result = await browser_monitor.route_browser_request("Use Computer for: Read my Gmail inbox", "agent:agt_mail:main")
            launch.assert_awaited_once_with("Read my Gmail inbox", "agent:agt_mail:main")
            return result
        result = asyncio.run(scenario())
        self.assertEqual(result["card"]["mode"], "qemu")


if __name__ == "__main__":
    unittest.main()
