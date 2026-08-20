from __future__ import annotations

import base64
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

DISTRO = os.getenv("AGENTIE_WSL_DISTRO", "Ubuntu")
KASMVNC_VERSION = os.getenv("AGENTIE_KASMVNC_VERSION", "1.5.0")
KASMVNC_PORT = int(os.getenv("AGENTIE_KASMVNC_PORT", "8444"))
_START_LOCK = threading.Lock()


def _windows_wsl() -> str | None:
    if os.name != "nt":
        return None
    return shutil.which("wsl.exe") or shutil.which("wsl")


def _run_wsl(script: str, timeout: int = 25, *, root: bool = False) -> subprocess.CompletedProcess[str]:
    executable = _windows_wsl()
    if not executable:
        raise RuntimeError("The real Agentie Computer requires Windows with WSL2.")
    payload = base64.b64encode(script.encode("utf-8")).decode("ascii")
    launcher = f"printf '%s' '{payload}' | base64 -d | bash"
    args = [executable, "-d", DISTRO]
    if root:
        args += ["-u", "root"]
    args += ["--", "bash", "-lc", launcher]
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, shell=False)


def _wsl_ip() -> str | None:
    try:
        proc = _run_wsl("hostname -I | awk '{print $1}'", timeout=8)
        value = (proc.stdout or "").strip().split()
        return value[0] if proc.returncode == 0 and value else None
    except Exception:
        return None


def _port_open(host: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_ready(url: str, timeout: float = 0.8) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= int(response.status) < 500
    except Exception:
        return False


def _urls(desktop_host: str | None, cdp_host: str | None) -> tuple[str | None, str | None]:
    desktop = f"http://{desktop_host}:{KASMVNC_PORT}/" if desktop_host else None
    cdp = f"http://{cdp_host}:9222" if cdp_host else None
    return desktop, cdp


def _reachable_endpoints(wsl_ip: str | None) -> tuple[str | None, str | None]:
    desktop_host = None
    cdp_host = None
    for host in ("127.0.0.1", wsl_ip):
        if host and not desktop_host and _port_open(host, KASMVNC_PORT):
            desktop_host = host
    for host in ("127.0.0.1", wsl_ip):
        if host and not cdp_host and _http_ready(f"http://{host}:9222/json/version"):
            cdp_host = host
    return desktop_host, cdp_host


def status() -> dict[str, Any]:
    supported = bool(_windows_wsl())
    wsl_ip = _wsl_ip() if supported else None
    desktop_host, cdp_host = _reachable_endpoints(wsl_ip) if supported else (None, None)
    desktop_url, cdp_url = _urls(desktop_host, cdp_host)
    return {
        "supported": supported,
        "running": bool(desktop_host),
        "novnc_ready": bool(desktop_host),
        "kasmvnc_ready": bool(desktop_host),
        "chrome_ready": bool(cdp_host),
        "novnc_url": desktop_url,
        "kasmvnc_url": desktop_url,
        "cdp_url": cdp_url,
        "distro": DISTRO,
        "wsl_ip": wsl_ip,
        "bridge_host": desktop_host,
        "novnc_host": desktop_host,
        "kasmvnc_host": desktop_host,
        "cdp_host": cdp_host,
    }


def _set_ini_option_preserving_text(text: str, section: str, key: str, value: str) -> str:
    lines = text.splitlines()
    section_re = re.compile(rf"^\s*\[{re.escape(section)}\]\s*$", re.I)
    key_re = re.compile(rf"^\s*{re.escape(key)}\s*=", re.I)
    section_start = None
    section_end = len(lines)
    for index, line in enumerate(lines):
        if section_re.match(line):
            section_start = index
            for end in range(index + 1, len(lines)):
                if re.match(r"^\s*\[[^]]+\]\s*$", lines[end]):
                    section_end = end
                    break
            break
    replacement = f"{key}={value}"
    if section_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([f"[{section}]", replacement])
        return "\n".join(lines) + "\n"
    for index in range(section_start + 1, section_end):
        if key_re.match(lines[index]):
            lines[index] = replacement
            return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    lines.insert(section_end, replacement)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def _ensure_mirrored_networking() -> bool:
    if os.name != "nt":
        return False
    path = Path.home() / ".wslconfig"
    try:
        original = path.read_text(encoding="utf-8") if path.exists() else ""
    except Exception:
        original = ""
    updated = _set_ini_option_preserving_text(original, "wsl2", "networkingMode", "mirrored")
    updated = _set_ini_option_preserving_text(updated, "wsl2", "localhostForwarding", "true")
    if updated == original:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def _shutdown_wsl() -> None:
    executable = _windows_wsl()
    if not executable:
        raise RuntimeError("WSL is not available.")
    proc = subprocess.run([executable, "--shutdown"], capture_output=True, text=True, timeout=20, shell=False)
    if proc.returncode != 0:
        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        raise RuntimeError("Could not restart WSL after networking setup: " + (output[-1000:] or f"exit {proc.returncode}"))
    time.sleep(2.0)


def _bootstrap_packages() -> None:
    script = rf'''
set -eu
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl xfce4 xfce4-terminal thunar dbus-x11 socat
if ! command -v vncserver >/dev/null 2>&1 || ! command -v Xkasmvnc >/dev/null 2>&1; then
  . /etc/os-release
  codename="${{VERSION_CODENAME:-${{UBUNTU_CODENAME:-}}}}"
  case "$codename" in focal|jammy|noble) ;; *) echo "Unsupported Ubuntu release for KasmVNC: $codename"; exit 44 ;; esac
  case "$(uname -m)" in x86_64) arch=amd64 ;; aarch64|arm64) arch=arm64 ;; *) echo "Unsupported architecture: $(uname -m)"; exit 45 ;; esac
  version="{KASMVNC_VERSION}"
  deb="kasmvncserver_${{codename}}_${{version}}_${{arch}}.deb"
  url="https://github.com/kasmtech/KasmVNC/releases/download/v${{version}}/${{deb}}"
  curl -fL --retry 3 "$url" -o "/tmp/$deb"
  apt-get install -y "/tmp/$deb"
  rm -f "/tmp/$deb"
fi
'''
    try:
        proc = _run_wsl(script, timeout=360, root=True)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("The one-time KasmVNC desktop installation timed out.") from exc
    if proc.returncode != 0:
        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        raise RuntimeError("Could not install the Agentie KasmVNC desktop: " + (output[-1800:] or f"exit {proc.returncode}"))


def _prepare_x11_runtime() -> None:
    script = rf'''
rm -f /tmp/.X1-lock 2>/dev/null || true
mkdir -p "$HOME/.vnc" "$HOME/.config/autostart" "$HOME/Desktop"
cat > "$HOME/.vnc/kasmvnc.yaml" <<'EOF'
desktop:
  resolution:
    width: 1440
    height: 900
  allow_resize: true
  pixel_depth: 24
network:
  protocol: http
  interface: 0.0.0.0
  websocket_port: {KASMVNC_PORT}
  use_ipv4: true
  use_ipv6: false
  udp:
    public_ip: 127.0.0.1
  ssl:
    require_ssl: false
command_line:
  prompt: false
EOF
cat > "$HOME/.config/autostart/xfce4-notifyd.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=XFCE Notify Daemon
Hidden=true
X-GNOME-Autostart-enabled=false
EOF
cat > "$HOME/Desktop/Chrome.desktop" <<'EOF'
[Desktop Entry]
Version=1.0
Type=Application
Name=Chrome
Comment=Browse the web
Exec=google-chrome --user-data-dir=%h/.agentie-chrome --no-first-run --no-default-browser-check
Icon=google-chrome
Terminal=false
Categories=Network;WebBrowser;
EOF
cat > "$HOME/Desktop/Terminal.desktop" <<'EOF'
[Desktop Entry]
Version=1.0
Type=Application
Name=Terminal
Comment=Open a Linux terminal
Exec=xfce4-terminal
Icon=utilities-terminal
Terminal=false
Categories=System;TerminalEmulator;
EOF
cat > "$HOME/Desktop/Files.desktop" <<'EOF'
[Desktop Entry]
Version=1.0
Type=Application
Name=Files
Comment=Browse files
Exec=thunar
Icon=system-file-manager
Terminal=false
Categories=System;FileManager;
EOF
cat > "$HOME/Desktop/Home.desktop" <<'EOF'
[Desktop Entry]
Version=1.0
Type=Application
Name=Home
Comment=Open your home folder
Exec=thunar %h
Icon=user-home
Terminal=false
Categories=System;FileManager;
EOF
chmod +x "$HOME/Desktop"/*.desktop
for shortcut in "$HOME/Desktop"/*.desktop; do gio set "$shortcut" metadata::trusted true >/dev/null 2>&1 || true; done
'''
    proc = _run_wsl(script, timeout=12)
    if proc.returncode != 0:
        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        raise RuntimeError("Could not prepare the Agentie desktop: " + (output[-1000:] or f"exit {proc.returncode}"))


def _start_script() -> str:
    return rf'''
set -u
missing=""
command -v vncserver >/dev/null 2>&1 || missing="$missing kasmvncserver"
command -v Xkasmvnc >/dev/null 2>&1 || missing="$missing Xkasmvnc"
command -v startxfce4 >/dev/null 2>&1 || missing="$missing xfce4"
command -v dbus-launch >/dev/null 2>&1 || missing="$missing dbus-x11"
command -v xfce4-terminal >/dev/null 2>&1 || missing="$missing xfce4-terminal"
command -v thunar >/dev/null 2>&1 || missing="$missing thunar"
if [ -n "$missing" ]; then echo "__MISSING__:$missing"; exit 42; fi
WSL_IP="$(hostname -I | awk '{{print $1}}')"
vncserver -kill :1 >/dev/null 2>&1 || true
pkill -f 'socat.*9222' >/dev/null 2>&1 || true
pkill -f 'google-chrome.*\.agentie-chrome' >/dev/null 2>&1 || true
rm -f /tmp/.X1-lock 2>/dev/null || true
sleep 0.3
nohup env -u WAYLAND_DISPLAY -u WAYLAND_SOCKET \
  XDG_SESSION_TYPE=x11 GDK_BACKEND=x11 QT_QPA_PLATFORM=xcb AGENTIE_DESKTOP=1 \
  vncserver :1 -select-de XFCE -geometry 1440x900 -depth 24 \
  -disableBasicAuth -SecurityTypes None \
  >/tmp/agentie-kasmvnc.log 2>&1 </dev/null &
for i in $(seq 1 120); do
  (echo >/dev/tcp/127.0.0.1/{KASMVNC_PORT}) >/dev/null 2>&1 && break
  sleep 0.2
done
if ! (echo >/dev/tcp/127.0.0.1/{KASMVNC_PORT}) >/dev/null 2>&1; then
  echo '__KASMVNC_ERROR__'; cat /tmp/agentie-kasmvnc.log 2>/dev/null || true; cat "$HOME/.vnc"/*.log 2>/dev/null || true; exit 55
fi
if command -v google-chrome >/dev/null 2>&1; then
  nohup env -u WAYLAND_DISPLAY -u WAYLAND_SOCKET DISPLAY=:1 XDG_SESSION_TYPE=x11 GDK_BACKEND=x11 \
    google-chrome --ozone-platform=x11 --user-data-dir="$HOME/.agentie-chrome" \
    --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 --remote-allow-origins=* \
    --no-first-run --no-default-browser-check --disable-gpu about:blank >/tmp/agentie-chrome.log 2>&1 </dev/null &
  for i in $(seq 1 30); do (echo >/dev/tcp/127.0.0.1/9222) >/dev/null 2>&1 && break; sleep 0.1; done
  if [ -n "$WSL_IP" ] && command -v socat >/dev/null 2>&1 && (echo >/dev/tcp/127.0.0.1/9222) >/dev/null 2>&1; then
    nohup socat TCP-LISTEN:9222,bind="$WSL_IP",reuseaddr,fork TCP:127.0.0.1:9222 >/tmp/agentie-cdp-bridge.log 2>&1 </dev/null &
  fi
fi
echo '__DESKTOP_READY__'
exit 0
'''


def _start_once() -> dict[str, Any]:
    _prepare_x11_runtime()
    try:
        proc = _run_wsl(_start_script(), timeout=45)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("The Agentie Computer took too long to start.") from exc
    output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if proc.returncode == 42 or "__MISSING__" in output:
        _bootstrap_packages()
        _prepare_x11_runtime()
        proc = _run_wsl(_start_script(), timeout=45)
        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if proc.returncode == 42 or "__MISSING__" in output:
        return {**status(), "setup_required": True, "message": "KasmVNC or a required desktop component is still missing inside Ubuntu.", "details": output[-1400:]}
    if proc.returncode != 0:
        raise RuntimeError("Could not start the Agentie KasmVNC desktop: " + (output[-3000:] or f"exit {proc.returncode}"))
    for _ in range(60):
        current = status()
        if current["novnc_ready"]:
            return {**current, "message": "Agentie Computer desktop started with KasmVNC."}
        time.sleep(0.25)
    return status()


def ensure_started() -> dict[str, Any]:
    with _START_LOCK:
        current = status()
        if current["novnc_ready"]:
            return {**current, "message": "Agentie Computer is ready."}
        first = _start_once()
        if first.get("novnc_ready") or first.get("setup_required"):
            return first
        changed = _ensure_mirrored_networking()
        if changed:
            _shutdown_wsl()
            second = _start_once()
            if second.get("novnc_ready"):
                return {**second, "message": "Agentie Computer started after enabling WSL mirrored networking."}
            if second.get("setup_required"):
                return second
        current = status()
        raise RuntimeError(f"Agentie started KasmVNC, but Windows cannot reach the visual desktop on port {KASMVNC_PORT}. WSL IP={current.get('wsl_ip') or 'unknown'}.")


def stop() -> dict[str, Any]:
    if not _windows_wsl():
        return {**status(), "message": "Agentie Computer is already stopped."}
    script = r'''
vncserver -kill :1 >/dev/null 2>&1 || true
pkill -f 'Xkasmvnc.*:1' >/dev/null 2>&1 || true
pkill -f 'socat.*9222' >/dev/null 2>&1 || true
pkill -f 'google-chrome.*\.agentie-chrome' >/dev/null 2>&1 || true
'''
    try:
        _run_wsl(script, timeout=12)
        _prepare_x11_runtime()
    except Exception:
        pass
    return {**status(), "running": False, "novnc_ready": False, "kasmvnc_ready": False, "chrome_ready": False, "novnc_url": None, "kasmvnc_url": None, "cdp_url": None, "message": "Agentie Computer stopped."}
