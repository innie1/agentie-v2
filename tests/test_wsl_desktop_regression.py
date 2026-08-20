import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import wsl_desktop


class WSLDesktopRegressionTests(unittest.TestCase):
    def test_urls_support_different_hosts(self):
        desktop, cdp = wsl_desktop._urls("127.0.0.1", "172.21.18.153")
        self.assertEqual(desktop, f"http://127.0.0.1:{wsl_desktop.KASMVNC_PORT}/")
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

    def test_prepare_builds_manual_x11_kasmvnc_home_and_shortcuts(self):
        calls = []
        def fake_run(script, timeout=25, root=False):
            calls.append((script, root))
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with patch.object(wsl_desktop, "_run_wsl", side_effect=fake_run):
            wsl_desktop._prepare_x11_runtime()
        self.assertEqual(len(calls), 1)
        script = calls[0][0]
        self.assertFalse(calls[0][1])
        self.assertIn("$HOME/.vnc/kasmvnc.yaml", script)
        self.assertIn(f"websocket_port: {wsl_desktop.KASMVNC_PORT}", script)
        self.assertIn("require_ssl: false", script)
        self.assertIn("prompt: false", script)
        self.assertIn("$HOME/.vnc/xstartup", script)
        self.assertIn("unset WAYLAND_DISPLAY", script)
        self.assertIn("XDG_SESSION_TYPE=x11", script)
        self.assertIn("startxfce4 --replace", script)
        self.assertIn('vncpasswd -u "$USER" -r', script)
        self.assertIn('vncpasswd -u "$USER" -w', script)
        self.assertIn("xfce4-notifyd.desktop", script)
        self.assertIn("$HOME/Desktop/Chrome.desktop", script)
        self.assertIn("$HOME/Desktop/Terminal.desktop", script)
        self.assertIn("$HOME/Desktop/Files.desktop", script)
        self.assertIn("$HOME/Desktop/Home.desktop", script)
        self.assertNotIn("chmod 1777 /tmp/.X11-unix", script)

    def test_start_script_uses_manual_kasmvnc_and_keeps_cdp_optional(self):
        script = wsl_desktop._start_script()
        self.assertIn("vncserver :1 -select-de manual", script)
        self.assertNotIn("-select-de XFCE", script)
        self.assertIn("-disableBasicAuth -SecurityTypes None", script)
        self.assertIn("xfce4-panel|xfdesktop|xfce4-session|xfwm4", script)
        self.assertIn("XDG_SESSION_TYPE=x11", script)
        self.assertIn(str(wsl_desktop.KASMVNC_PORT), script)
        self.assertIn("__DESKTOP_READY__", script)
        self.assertIn("if command -v google-chrome", script)
        self.assertNotIn("websockify", script)
        self.assertNotIn("Xtigervnc", script)
        self.assertNotIn("/usr/share/novnc", script)

    def test_bootstrap_installs_kasmvnc_desktop_apps_and_ssl_cert(self):
        with patch.object(wsl_desktop, "_run_wsl", return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")) as runner:
            wsl_desktop._bootstrap_packages()
        command = runner.call_args.args[0]
        self.assertIn("kasmvncserver_", command)
        self.assertIn(wsl_desktop.KASMVNC_VERSION, command)
        self.assertIn("ssl-cert", command)
        self.assertIn("xfce4-terminal", command)
        self.assertIn("thunar", command)
        self.assertIn("socat", command)
        self.assertNotIn("tigervnc-standalone-server", command)
        self.assertNotIn("websockify", command)

    def test_system_runtime_repairs_ssl_cert_and_group(self):
        with patch.object(wsl_desktop, "_run_wsl", return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")) as runner:
            wsl_desktop._ensure_system_runtime()
        command = runner.call_args.args[0]
        self.assertIn("ssl-cert-snakeoil.key", command)
        self.assertIn("apt-get install -y ssl-cert", command)
        self.assertIn('adduser "$agentie_user" ssl-cert', command)
        self.assertTrue(runner.call_args.kwargs["root"])

    def test_status_desktop_can_be_ready_when_cdp_is_not(self):
        def port_open(host, port):
            return host == "127.0.0.1" and port == wsl_desktop.KASMVNC_PORT
        with patch.object(wsl_desktop, "_windows_wsl", return_value="wsl.exe"), \
             patch.object(wsl_desktop, "_wsl_ip", return_value="192.168.1.14"), \
             patch.object(wsl_desktop, "_port_open", side_effect=port_open), \
             patch.object(wsl_desktop, "_http_ready", return_value=False):
            result = wsl_desktop.status()
        self.assertTrue(result["running"])
        self.assertTrue(result["novnc_ready"])
        self.assertTrue(result["kasmvnc_ready"])
        self.assertFalse(result["chrome_ready"])
        self.assertEqual(result["kasmvnc_host"], "127.0.0.1")
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
        ready = {"supported": True, "running": True, "novnc_ready": True, "kasmvnc_ready": True, "chrome_ready": False, "novnc_url": "http://127.0.0.1:8444/", "kasmvnc_url": "http://127.0.0.1:8444/", "cdp_url": None, "distro": "Ubuntu", "wsl_ip": "192.168.1.14", "bridge_host": "127.0.0.1", "novnc_host": "127.0.0.1", "kasmvnc_host": "127.0.0.1", "cdp_host": None}
        with patch.object(wsl_desktop, "status", return_value=ready), patch.object(wsl_desktop, "_run_wsl") as runner, patch.object(wsl_desktop, "_prepare_x11_runtime") as prepare, patch.object(wsl_desktop, "_ensure_system_runtime") as system:
            result = wsl_desktop.ensure_started()
        runner.assert_not_called()
        prepare.assert_not_called()
        system.assert_not_called()
        self.assertTrue(result["running"])
        self.assertFalse(result["chrome_ready"])

    def test_start_once_prepares_system_and_returns_when_visual_desktop_is_ready(self):
        started = subprocess.CompletedProcess([], 0, stdout="__DESKTOP_READY__", stderr="")
        ready = {"supported": True, "running": True, "novnc_ready": True, "kasmvnc_ready": True, "chrome_ready": False, "novnc_url": "http://127.0.0.1:8444/", "kasmvnc_url": "http://127.0.0.1:8444/", "cdp_url": None, "distro": "Ubuntu", "wsl_ip": "192.168.1.14", "bridge_host": "127.0.0.1", "novnc_host": "127.0.0.1", "kasmvnc_host": "127.0.0.1", "cdp_host": None}
        with patch.object(wsl_desktop, "_run_wsl", return_value=started), patch.object(wsl_desktop, "_ensure_system_runtime") as system, patch.object(wsl_desktop, "_prepare_x11_runtime") as prepare, patch.object(wsl_desktop, "status", return_value=ready):
            result = wsl_desktop._start_once()
        system.assert_called_once()
        prepare.assert_called_once()
        self.assertTrue(result["kasmvnc_ready"])
        self.assertFalse(result["chrome_ready"])

    def test_stop_kills_kasmvnc_xfce_and_optional_cdp_bridge(self):
        stopped = {"supported": True, "running": False, "novnc_ready": False, "kasmvnc_ready": False, "chrome_ready": False, "novnc_url": None, "kasmvnc_url": None, "cdp_url": None, "distro": "Ubuntu", "wsl_ip": "192.168.1.14", "bridge_host": None, "novnc_host": None, "kasmvnc_host": None, "cdp_host": None}
        with patch.object(wsl_desktop, "_windows_wsl", return_value="wsl.exe"), patch.object(wsl_desktop, "_run_wsl", return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")) as runner, patch.object(wsl_desktop, "_prepare_x11_runtime") as prepare, patch.object(wsl_desktop, "status", return_value=stopped):
            result = wsl_desktop.stop()
        script = runner.call_args.args[0]
        self.assertIn("vncserver -kill :1", script)
        self.assertIn("xfce4-panel|xfdesktop|xfce4-session|xfwm4", script)
        self.assertIn("socat.*9222", script)
        prepare.assert_called_once()
        self.assertFalse(result["running"])


if __name__ == "__main__":
    unittest.main()
