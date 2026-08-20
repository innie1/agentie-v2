import subprocess
import unittest
from unittest.mock import patch

from agentie.core import wsl_desktop


class WSLDesktopRegressionTests(unittest.TestCase):
    def test_urls_use_selected_bridge_host(self):
        novnc, cdp = wsl_desktop._urls("127.0.0.1")
        self.assertTrue(novnc.startswith("http://127.0.0.1:6080/"))
        self.assertEqual(cdp, "http://127.0.0.1:9222")

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

    def test_start_script_uses_tcp_x_and_forwardable_bridge(self):
        script = wsl_desktop._start_script()
        self.assertIn("-nolisten unix -listen tcp -noreset", script)
        self.assertIn("DISPLAY=127.0.0.1:1", script)
        self.assertIn("0.0.0.0:6080", script)
        self.assertIn("--remote-debugging-address=0.0.0.0", script)
        self.assertIn("--remote-allow-origins=*", script)
        self.assertNotIn("chmod 1777 /tmp/.X11-unix", script)

    def test_start_script_does_not_probe_vnc_by_connecting_to_5901(self):
        script = wsl_desktop._start_script()
        self.assertNotIn("echo >/dev/tcp/127.0.0.1/5901", script)
        self.assertIn("kill -0 \"$vnc_pid\"", script)

    def test_status_prefers_windows_localhost_forwarding(self):
        with patch.object(wsl_desktop, "_windows_wsl", return_value="wsl.exe"), \
             patch.object(wsl_desktop, "_wsl_ip", return_value="172.21.18.153"), \
             patch.object(wsl_desktop, "_port_open", return_value=True) as port_open, \
             patch.object(wsl_desktop, "_http_ready", return_value=True) as http_ready:
            result = wsl_desktop.status()
        port_open.assert_called_once_with("127.0.0.1", 6080)
        http_ready.assert_called_once_with("http://127.0.0.1:9222/json/version")
        self.assertEqual(result["bridge_host"], "127.0.0.1")
        self.assertEqual(result["wsl_ip"], "172.21.18.153")
        self.assertTrue(result["running"])

    def test_status_falls_back_to_wsl_ip_when_localhost_unavailable(self):
        def port_open(host, port):
            return host == "172.21.18.153" and port == 6080
        def http_ready(url):
            return url == "http://172.21.18.153:9222/json/version"
        with patch.object(wsl_desktop, "_windows_wsl", return_value="wsl.exe"), \
             patch.object(wsl_desktop, "_wsl_ip", return_value="172.21.18.153"), \
             patch.object(wsl_desktop, "_port_open", side_effect=port_open), \
             patch.object(wsl_desktop, "_http_ready", side_effect=http_ready):
            result = wsl_desktop.status()
        self.assertEqual(result["bridge_host"], "172.21.18.153")
        self.assertTrue(result["running"])

    def test_ready_desktop_does_not_restart(self):
        ready = {"supported": True, "running": True, "novnc_ready": True, "chrome_ready": True, "novnc_url": "http://127.0.0.1:6080/vnc_lite.html", "cdp_url": "http://127.0.0.1:9222", "distro": "Ubuntu", "wsl_ip": "172.21.18.153", "bridge_host": "127.0.0.1"}
        with patch.object(wsl_desktop, "status", return_value=ready), patch.object(wsl_desktop, "_run_wsl") as runner, patch.object(wsl_desktop, "_prepare_x11_runtime") as prepare:
            result = wsl_desktop.ensure_started()
        runner.assert_not_called()
        prepare.assert_not_called()
        self.assertTrue(result["running"])

    def test_missing_bridge_packages_bootstrap_once(self):
        missing = subprocess.CompletedProcess([], 42, stdout="__MISSING__: Xtigervnc websockify novnc", stderr="")
        started = subprocess.CompletedProcess([], 0, stdout="__READY__", stderr="")
        not_ready = {"supported": True, "running": False, "novnc_ready": False, "chrome_ready": False, "novnc_url": None, "cdp_url": None, "distro": "Ubuntu", "wsl_ip": "172.21.18.153", "bridge_host": None}
        ready = {"supported": True, "running": True, "novnc_ready": True, "chrome_ready": True, "novnc_url": "http://127.0.0.1:6080/vnc_lite.html", "cdp_url": "http://127.0.0.1:9222", "distro": "Ubuntu", "wsl_ip": "172.21.18.153", "bridge_host": "127.0.0.1"}
        with patch.object(wsl_desktop, "status", side_effect=[not_ready, ready]), patch.object(wsl_desktop, "_run_wsl", side_effect=[missing, started]), patch.object(wsl_desktop, "_bootstrap_packages") as bootstrap, patch.object(wsl_desktop, "_prepare_x11_runtime") as prepare:
            result = wsl_desktop.ensure_started()
        bootstrap.assert_called_once()
        self.assertEqual(prepare.call_count, 2)
        self.assertTrue(result["running"])

    def test_stop_kills_desktop_services(self):
        stopped = {"supported": True, "running": False, "novnc_ready": False, "chrome_ready": False, "novnc_url": None, "cdp_url": None, "distro": "Ubuntu", "wsl_ip": "172.21.18.153", "bridge_host": None}
        with patch.object(wsl_desktop, "_windows_wsl", return_value="wsl.exe"), patch.object(wsl_desktop, "_run_wsl", return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")) as runner, patch.object(wsl_desktop, "_prepare_x11_runtime") as prepare, patch.object(wsl_desktop, "status", return_value=stopped):
            result = wsl_desktop.stop()
        self.assertEqual(runner.call_count, 1)
        prepare.assert_called_once()
        self.assertFalse(result["running"])


if __name__ == "__main__":
    unittest.main()
