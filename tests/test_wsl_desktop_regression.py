import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import wsl_desktop


class WSLDesktopRegressionTests(unittest.TestCase):
    def test_urls_support_different_hosts(self):
        novnc, cdp = wsl_desktop._urls("127.0.0.1", "172.21.18.153")
        self.assertTrue(novnc.startswith("http://127.0.0.1:6080/"))
        self.assertEqual(cdp, "http://172.21.18.153:9222")

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

    def test_prepare_builds_clean_agentie_home(self):
        calls = []
        def fake_run(script, timeout=25, root=False):
            calls.append((script, root))
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with patch.object(wsl_desktop, "_run_wsl", side_effect=fake_run):
            wsl_desktop._prepare_x11_runtime()
        self.assertEqual(len(calls), 1)
        script = calls[0][0]
        self.assertFalse(calls[0][1])
        self.assertIn("rm -f /tmp/.X1-lock", script)
        self.assertNotIn("chmod 1777 /tmp/.X11-unix", script)
        self.assertIn("xfce4-notifyd.desktop", script)
        self.assertIn("$HOME/Desktop/Chrome.desktop", script)
        self.assertIn("$HOME/Desktop/Terminal.desktop", script)
        self.assertIn("$HOME/Desktop/Files.desktop", script)
        self.assertIn("$HOME/Desktop/Home.desktop", script)

    def test_start_script_makes_desktop_primary_and_cdp_optional(self):
        script = wsl_desktop._start_script()
        self.assertIn("-nolisten unix -listen tcp -noreset", script)
        self.assertIn("DISPLAY=127.0.0.1:1", script)
        self.assertIn("0.0.0.0:6080", script)
        self.assertIn("__DESKTOP_READY__", script)
        self.assertIn("if command -v google-chrome", script)
        self.assertNotIn("__CHROME_ERROR__", script)
        self.assertNotIn("chmod 1777 /tmp/.X11-unix", script)

    def test_bootstrap_installs_desktop_apps(self):
        with patch.object(wsl_desktop, "_run_wsl", return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")) as runner:
            wsl_desktop._bootstrap_packages()
        command = runner.call_args.args[0]
        self.assertIn("xfce4-terminal", command)
        self.assertIn("thunar", command)
        self.assertIn("socat", command)

    def test_status_desktop_can_be_ready_when_cdp_is_not(self):
        def port_open(host, port):
            return host == "127.0.0.1" and port == 6080
        with patch.object(wsl_desktop, "_windows_wsl", return_value="wsl.exe"), \
             patch.object(wsl_desktop, "_wsl_ip", return_value="192.168.1.14"), \
             patch.object(wsl_desktop, "_port_open", side_effect=port_open), \
             patch.object(wsl_desktop, "_http_ready", return_value=False):
            result = wsl_desktop.status()
        self.assertTrue(result["running"])
        self.assertTrue(result["novnc_ready"])
        self.assertFalse(result["chrome_ready"])
        self.assertEqual(result["novnc_host"], "127.0.0.1")
        self.assertIsNone(result["cdp_host"])

    def test_mirrored_networking_preserves_existing_wslconfig(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            config = home / ".wslconfig"
            config.write_text("[wsl2]\nmemory=4GB\n\n[experimental]\nautoMemoryReclaim=gradual\n", encoding="utf-8")
            with patch.object(wsl_desktop.os, "name", "nt"), patch.object(wsl_desktop.Path, "home", return_value=home):
                changed = wsl_desktop._ensure_mirrored_networking()
            text = config.read_text(encoding="utf-8")
        self.assertTrue(changed)
        self.assertIn("memory=4GB", text)
        self.assertIn("autoMemoryReclaim=gradual", text)
        self.assertIn("networkingMode=mirrored", text)
        self.assertIn("localhostForwarding=true", text)

    def test_ready_desktop_does_not_restart_when_chrome_cdp_is_down(self):
        ready = {"supported": True, "running": True, "novnc_ready": True, "chrome_ready": False, "novnc_url": "http://127.0.0.1:6080/vnc_lite.html", "cdp_url": None, "distro": "Ubuntu", "wsl_ip": "192.168.1.14", "bridge_host": "127.0.0.1", "novnc_host": "127.0.0.1", "cdp_host": None}
        with patch.object(wsl_desktop, "status", return_value=ready), patch.object(wsl_desktop, "_run_wsl") as runner, patch.object(wsl_desktop, "_prepare_x11_runtime") as prepare:
            result = wsl_desktop.ensure_started()
        runner.assert_not_called()
        prepare.assert_not_called()
        self.assertTrue(result["running"])
        self.assertFalse(result["chrome_ready"])

    def test_start_once_returns_when_visual_desktop_is_ready(self):
        started = subprocess.CompletedProcess([], 0, stdout="__DESKTOP_READY__", stderr="")
        ready = {"supported": True, "running": True, "novnc_ready": True, "chrome_ready": False, "novnc_url": "http://127.0.0.1:6080/vnc_lite.html", "cdp_url": None, "distro": "Ubuntu", "wsl_ip": "192.168.1.14", "bridge_host": "127.0.0.1", "novnc_host": "127.0.0.1", "cdp_host": None}
        with patch.object(wsl_desktop, "_run_wsl", return_value=started), patch.object(wsl_desktop, "_prepare_x11_runtime"), patch.object(wsl_desktop, "status", return_value=ready):
            result = wsl_desktop._start_once()
        self.assertTrue(result["novnc_ready"])
        self.assertFalse(result["chrome_ready"])

    def test_stop_kills_optional_cdp_bridge_too(self):
        stopped = {"supported": True, "running": False, "novnc_ready": False, "chrome_ready": False, "novnc_url": None, "cdp_url": None, "distro": "Ubuntu", "wsl_ip": "192.168.1.14", "bridge_host": None, "novnc_host": None, "cdp_host": None}
        with patch.object(wsl_desktop, "_windows_wsl", return_value="wsl.exe"), patch.object(wsl_desktop, "_run_wsl", return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")) as runner, patch.object(wsl_desktop, "_prepare_x11_runtime") as prepare, patch.object(wsl_desktop, "status", return_value=stopped):
            result = wsl_desktop.stop()
        self.assertIn("socat.*9222", runner.call_args.args[0])
        prepare.assert_called_once()
        self.assertFalse(result["running"])


if __name__ == "__main__":
    unittest.main()
