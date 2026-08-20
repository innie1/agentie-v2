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

    def test_x11_runtime_cleanup_does_not_touch_wslg_socket_or_require_root(self):
        calls = []
        def fake_run(script, timeout=25, root=False):
            calls.append((script, root))
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with patch.object(wsl_desktop, "_run_wsl", side_effect=fake_run):
            wsl_desktop._prepare_x11_runtime()
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0][1])
        self.assertIn("rm -f /tmp/.X1-lock", calls[0][0])
        self.assertNotIn("chmod 1777 /tmp/.X11-unix", calls[0][0])

    def test_start_script_bridges_cdp_separately(self):
        script = wsl_desktop._start_script()
        self.assertIn("-nolisten unix -listen tcp -noreset", script)
        self.assertIn("DISPLAY=127.0.0.1:1", script)
        self.assertIn("0.0.0.0:6080", script)
        self.assertIn("--remote-debugging-address=127.0.0.1", script)
        self.assertIn("socat TCP-LISTEN:9222", script)
        self.assertIn('bind="$WSL_IP"', script)
        self.assertIn("TCP:127.0.0.1:9222", script)
        self.assertNotIn("chmod 1777 /tmp/.X11-unix", script)

    def test_bootstrap_installs_socat(self):
        with patch.object(wsl_desktop, "_run_wsl", return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")) as runner:
            wsl_desktop._bootstrap_packages()
        self.assertIn("socat", runner.call_args.args[0])

    def test_status_can_use_localhost_for_novnc_and_wsl_ip_for_cdp(self):
        def port_open(host, port):
            return host == "127.0.0.1" and port == 6080
        def http_ready(url):
            return url == "http://172.21.18.153:9222/json/version"
        with patch.object(wsl_desktop, "_windows_wsl", return_value="wsl.exe"), \
             patch.object(wsl_desktop, "_wsl_ip", return_value="172.21.18.153"), \
             patch.object(wsl_desktop, "_port_open", side_effect=port_open), \
             patch.object(wsl_desktop, "_http_ready", side_effect=http_ready):
            result = wsl_desktop.status()
        self.assertEqual(result["novnc_host"], "127.0.0.1")
        self.assertEqual(result["cdp_host"], "172.21.18.153")
        self.assertTrue(result["novnc_ready"])
        self.assertTrue(result["chrome_ready"])
        self.assertTrue(result["running"])
        self.assertEqual(result["cdp_url"], "http://172.21.18.153:9222")

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

    def test_ready_desktop_does_not_restart(self):
        ready = {"supported": True, "running": True, "novnc_ready": True, "chrome_ready": True, "novnc_url": "http://127.0.0.1:6080/vnc_lite.html", "cdp_url": "http://172.21.18.153:9222", "distro": "Ubuntu", "wsl_ip": "172.21.18.153", "bridge_host": "127.0.0.1", "novnc_host": "127.0.0.1", "cdp_host": "172.21.18.153"}
        with patch.object(wsl_desktop, "status", return_value=ready), patch.object(wsl_desktop, "_run_wsl") as runner, patch.object(wsl_desktop, "_prepare_x11_runtime") as prepare:
            result = wsl_desktop.ensure_started()
        runner.assert_not_called()
        prepare.assert_not_called()
        self.assertTrue(result["running"])

    def test_missing_bridge_packages_bootstrap_once(self):
        missing = subprocess.CompletedProcess([], 42, stdout="__MISSING__: socat", stderr="")
        started = subprocess.CompletedProcess([], 0, stdout="__READY__:172.21.18.153", stderr="")
        not_ready = {"supported": True, "running": False, "novnc_ready": False, "chrome_ready": False, "novnc_url": None, "cdp_url": None, "distro": "Ubuntu", "wsl_ip": "172.21.18.153", "bridge_host": None, "novnc_host": None, "cdp_host": None}
        ready = {"supported": True, "running": True, "novnc_ready": True, "chrome_ready": True, "novnc_url": "http://127.0.0.1:6080/vnc_lite.html", "cdp_url": "http://172.21.18.153:9222", "distro": "Ubuntu", "wsl_ip": "172.21.18.153", "bridge_host": "127.0.0.1", "novnc_host": "127.0.0.1", "cdp_host": "172.21.18.153"}
        with patch.object(wsl_desktop, "status", side_effect=[not_ready, ready]), patch.object(wsl_desktop, "_run_wsl", side_effect=[missing, started]), patch.object(wsl_desktop, "_bootstrap_packages") as bootstrap, patch.object(wsl_desktop, "_prepare_x11_runtime") as prepare:
            result = wsl_desktop._start_once()
        bootstrap.assert_called_once()
        self.assertEqual(prepare.call_count, 2)
        self.assertTrue(result["running"])

    def test_stop_kills_cdp_bridge(self):
        stopped = {"supported": True, "running": False, "novnc_ready": False, "chrome_ready": False, "novnc_url": None, "cdp_url": None, "distro": "Ubuntu", "wsl_ip": "172.21.18.153", "bridge_host": None, "novnc_host": None, "cdp_host": None}
        with patch.object(wsl_desktop, "_windows_wsl", return_value="wsl.exe"), patch.object(wsl_desktop, "_run_wsl", return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")) as runner, patch.object(wsl_desktop, "_prepare_x11_runtime") as prepare, patch.object(wsl_desktop, "status", return_value=stopped):
            result = wsl_desktop.stop()
        self.assertIn("socat.*9222", runner.call_args.args[0])
        prepare.assert_called_once()
        self.assertFalse(result["running"])


if __name__ == "__main__":
    unittest.main()
