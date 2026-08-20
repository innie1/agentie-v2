import subprocess
import unittest
from unittest.mock import patch

from agentie.core import wsl_desktop


class WSLDesktopRegressionTests(unittest.TestCase):
    def test_novnc_is_localhost_only(self):
        self.assertTrue(wsl_desktop.NOVNC_URL.startswith("http://127.0.0.1:6080/"))
        self.assertEqual(wsl_desktop.CDP_URL, "http://127.0.0.1:9222")

    def test_wsl_script_is_base64_marshaled(self):
        captured = {}

        def fake_run(args, **kwargs):
            captured["args"] = args
            return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

        with patch.object(wsl_desktop, "_windows_wsl", return_value="wsl.exe"), patch.object(subprocess, "run", side_effect=fake_run):
            wsl_desktop._run_wsl("echo hello >/tmp/x 2>&1")

        launcher = captured["args"][-1]
        self.assertIn("base64 -d | bash", launcher)
        self.assertNotIn("2>&1", launcher)
        self.assertNotIn(">/tmp/x", launcher)

    def test_x11_runtime_repair_is_root_only_and_sets_sticky_mode(self):
        calls = []

        def fake_run(script, timeout=25, root=False):
            calls.append((script, root))
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")

        with patch.object(wsl_desktop, "_run_wsl", side_effect=fake_run):
            wsl_desktop._prepare_x11_runtime()

        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][1])
        self.assertIn("chmod 1777 /tmp/.X11-unix", calls[0][0])
        self.assertIn("rm -f /tmp/.X1-lock /tmp/.X11-unix/X1", calls[0][0])

    def test_start_script_does_not_copy_xstartup_onto_itself(self):
        script = wsl_desktop._start_script()
        self.assertNotIn("cp \"$HOME/.config/tigervnc/xstartup\"", script)
        self.assertIn("exec dbus-launch --exit-with-session startxfce4", script)

    def test_ready_desktop_does_not_restart(self):
        ready = {"supported": True, "running": True, "novnc_ready": True, "chrome_ready": True, "novnc_url": wsl_desktop.NOVNC_URL, "cdp_url": wsl_desktop.CDP_URL, "distro": "Ubuntu"}
        with patch.object(wsl_desktop, "status", return_value=ready), patch.object(wsl_desktop, "_run_wsl") as runner, patch.object(wsl_desktop, "_prepare_x11_runtime") as prepare:
            result = wsl_desktop.ensure_started()
        runner.assert_not_called()
        prepare.assert_not_called()
        self.assertTrue(result["running"])

    def test_missing_bridge_packages_bootstrap_once(self):
        missing = subprocess.CompletedProcess([], 42, stdout="__MISSING__: tigervncserver websockify novnc", stderr="")
        started = subprocess.CompletedProcess([], 0, stdout="__READY__", stderr="")
        not_ready = {"supported": True, "running": False, "novnc_ready": False, "chrome_ready": False, "novnc_url": None, "cdp_url": None, "distro": "Ubuntu"}
        ready = {"supported": True, "running": True, "novnc_ready": True, "chrome_ready": True, "novnc_url": wsl_desktop.NOVNC_URL, "cdp_url": wsl_desktop.CDP_URL, "distro": "Ubuntu"}
        with patch.object(wsl_desktop, "status", side_effect=[not_ready, ready]), patch.object(wsl_desktop, "_run_wsl", side_effect=[missing, started]), patch.object(wsl_desktop, "_bootstrap_packages") as bootstrap, patch.object(wsl_desktop, "_prepare_x11_runtime") as prepare:
            result = wsl_desktop.ensure_started()
        bootstrap.assert_called_once()
        self.assertEqual(prepare.call_count, 2)
        self.assertTrue(result["running"])

    def test_stop_kills_desktop_services(self):
        stopped = {"supported": True, "running": False, "novnc_ready": False, "chrome_ready": False, "novnc_url": None, "cdp_url": None, "distro": "Ubuntu"}
        with patch.object(wsl_desktop, "_windows_wsl", return_value="wsl.exe"), patch.object(wsl_desktop, "_run_wsl", return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")) as runner, patch.object(wsl_desktop, "_prepare_x11_runtime") as prepare, patch.object(wsl_desktop, "status", return_value=stopped):
            result = wsl_desktop.stop()
        self.assertEqual(runner.call_count, 1)
        prepare.assert_called_once()
        self.assertFalse(result["running"])


if __name__ == "__main__":
    unittest.main()
