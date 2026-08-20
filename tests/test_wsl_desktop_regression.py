import subprocess
import unittest
from unittest.mock import patch

from agentie.core import wsl_desktop


class WSLDesktopRegressionTests(unittest.TestCase):
    def test_novnc_is_localhost_only(self):
        self.assertTrue(wsl_desktop.NOVNC_URL.startswith("http://127.0.0.1:6080/"))
        self.assertEqual(wsl_desktop.CDP_URL, "http://127.0.0.1:9222")

    def test_ready_desktop_does_not_restart(self):
        ready = {"supported": True, "running": True, "novnc_ready": True, "chrome_ready": True, "novnc_url": wsl_desktop.NOVNC_URL, "cdp_url": wsl_desktop.CDP_URL, "distro": "Ubuntu"}
        with patch.object(wsl_desktop, "status", return_value=ready), patch.object(wsl_desktop, "_run_wsl") as runner:
            result = wsl_desktop.ensure_started()
        runner.assert_not_called()
        self.assertTrue(result["running"])

    def test_missing_bridge_packages_bootstrap_once(self):
        missing = subprocess.CompletedProcess([], 42, stdout="__MISSING__: tigervncserver websockify novnc", stderr="")
        started = subprocess.CompletedProcess([], 0, stdout="__READY__", stderr="")
        not_ready = {"supported": True, "running": False, "novnc_ready": False, "chrome_ready": False, "novnc_url": None, "cdp_url": None, "distro": "Ubuntu"}
        ready = {"supported": True, "running": True, "novnc_ready": True, "chrome_ready": True, "novnc_url": wsl_desktop.NOVNC_URL, "cdp_url": wsl_desktop.CDP_URL, "distro": "Ubuntu"}
        with patch.object(wsl_desktop, "status", side_effect=[not_ready, ready]), patch.object(wsl_desktop, "_run_wsl", side_effect=[missing, started]), patch.object(wsl_desktop, "_bootstrap_packages") as bootstrap:
            result = wsl_desktop.ensure_started()
        bootstrap.assert_called_once()
        self.assertTrue(result["running"])

    def test_stop_kills_desktop_services(self):
        stopped = {"supported": True, "running": False, "novnc_ready": False, "chrome_ready": False, "novnc_url": None, "cdp_url": None, "distro": "Ubuntu"}
        with patch.object(wsl_desktop, "_windows_wsl", return_value="wsl.exe"), patch.object(wsl_desktop, "_run_wsl", return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")) as runner, patch.object(wsl_desktop, "status", return_value=stopped):
            result = wsl_desktop.stop()
        self.assertEqual(runner.call_count, 1)
        self.assertFalse(result["running"])


if __name__ == "__main__":
    unittest.main()
