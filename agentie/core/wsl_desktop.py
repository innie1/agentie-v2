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


def _http_ready(url: str, timeout: float = 0.6) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= int(response.status) < 500
    except Exception:
        return False


def _urls(novnc_host: str | None, cdp_host: str | None) -> tuple[str | None, str | None]:
    novnc = f"http://{novnc_host}:6080/vnc_lite.html?autoconnect=1&resize=scale&reconnect=1&path=websockify" if novnc_host else None
    cdp = f"http://{cdp_host}:9222" if cdp_host else None
    return novnc, cdp


def _reachable_endpoints(wsl_ip: str | None) -> tuple[str | None, str | None]:
    novnc_host = None
    cdp_host = None
    for host in ("127.0.0.1", wsl_ip):
        if host and not novnc_host and _port_open(host, 6080):
            novnc_host = host
    for host in ("127.0.0.1", wsl_ip):
        if host and not cdp_host and _http_ready(f"http://{host}:9222/json/version"):
            cdp_host = host
    return novnc_host, cdp_host


def status() -> dict[str, Any]:
    supported = bool(_windows_wsl())
    wsl_ip = _wsl_ip() if supported else None
    novnc_host, cdp_host = _reachable_endpoints(wsl_ip) if supported else (None, None)
    novnc_url, cdp_url = _urls(novnc_host, cdp_host)
    return {
        "supported": supported,
        "running": bool(novnc_host),
        "novnc_ready": bool(novnc_host),
        "chrome_ready": bool(cdp_host),
        "novnc_url": novnc_url,
        "cdp_url": cdp_url,
        "distro": DISTRO,
        "wsl_ip": wsl_ip,
        "bridge_host": novnc_host,
        "novnc_host": novnc_host,
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
    script = "DEBIAN_FRONTEND=noninteractive apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y tigervnc-standalone-server tigervnc-tools novnc websockify xfce4 xfce4-terminal thunar dbus-x11 socat"
    try:
        proc = _run_wsl(script, timeout=300, root=True)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("The one-time Agentie desktop package installation timed out.") from exc
    if proc.returncode != 0:
        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        raise RuntimeError("Could not install the Agentie desktop bridge packages: " + (output[-1400:] or f"exit {proc.returncode}"))


def _prepare_x11_runtime() -> None:
    script = r'''
rm -f /tmp/.X1-lock 2>/dev/null || true
rm -f "$HOME/.config/tigervnc"/*:1.pid "$HOME/.config/tigervnc"/*:1.log 2>/dev/null || true

# Keep the Agentie desktop clean under WSL. xfce4-notifyd currently detects
# WSLg's Wayland environment and can show an irrelevant layer-shell warning.
mkdir -p "$HOME/.config/autostart" "$HOME/Desktop"
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
gio set "$HOME/Desktop/Chrome.desktop" metadata::trusted true >/dev/null 2>&1 || true
gio set "$HOME/Desktop/Terminal.desktop" metadata::trusted true >/dev/null 2>&1 || true
gio set "$HOME/Desktop/Files.desktop" metadata::trusted true >/dev/null 2>&1 || true
gio set "$HOME/Desktop/Home.desktop" metadata::trusted true >/dev/null 2>&1 || true
'''
    proc = _run_wsl(script, timeout=12)
    if proc.returncode != 0:
        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        raise RuntimeError("Could not prepare the Agentie desktop: " + (output[-1000:] or f"exit {proc.returncode}"))


def _start_script() -> str:
    return r'''
set -u
missing=""
command -v Xtigervnc >/dev/null 2>&1 || missing="$missing Xtigervnc"
command -v websockify >/dev/null 2>&1 || missing="$missing websockify"
[ -d /usr/share/novnc ] || missing="$missing novnc"
command -v startxfce4 >/dev/null 2>&1 || missing="$missing xfce4"
command -v dbus-launch >/dev/null 2>&1 || missing="$missing dbus-x11"
command -v xfce4-terminal >/dev/null 2>&1 || missing="$missing xfce4-terminal"
command -v thunar >/dev/null 2>&1 || missing="$missing thunar"
if [ -n "$missing" ]; then echo "__MISSING__:$missing"; exit 42; fi

WSL_IP="$(hostname -I | awk '{print $1}')"

pkill -f 'Xtigervnc.*:1' >/dev/null 2>&1 || true
pkill -f 'websockify.*6080' >/dev/null 2>&1 || true
pkill -f 'socat.*9222' >/dev/null 2>&1 || true
pkill -f 'google-chrome.*\.agentie-chrome' >/dev/null 2>&1 || true
pkill -f 'AGENTIE_DESKTOP=1.*startxfce4' >/dev/null 2>&1 || true
sleep 0.3

nohup Xtigervnc :1 \
  -geometry 1440x900 -depth 24 \
  -localhost yes -SecurityTypes None \
  -nolisten unix -listen tcp -noreset \
  >/tmp/agentie-vnc.log 2>&1 </dev/null &
vnc_pid=$!

for i in $(seq 1 50); do
  if ! kill -0 "$vnc_pid" 2>/dev/null; then
    echo '__VNC_ERROR__'; cat /tmp/agentie-vnc.log 2>/dev/null || true; exit 55
  fi
  if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ':5901 '; then break; fi
  sleep 0.1
done
if ! kill -0 "$vnc_pid" 2>/dev/null; then
  echo '__VNC_ERROR__'; cat /tmp/agentie-vnc.log 2>/dev/null || true; exit 55
fi

nohup env \
  -u WAYLAND_DISPLAY -u WAYLAND_SOCKET \
  DISPLAY=127.0.0.1:1 \
  XDG_SESSION_TYPE=x11 GDK_BACKEND=x11 QT_QPA_PLATFORM=xcb \
  AGENTIE_DESKTOP=1 \
  dbus-launch --exit-with-session startxfce4 \
  >/tmp/agentie-xfce.log 2>&1 </dev/null &

nohup websockify --web=/usr/share/novnc 0.0.0.0:6080 127.0.0.1:5901 >/tmp/agentie-novnc.log 2>&1 </dev/null &

# Chrome automation is optional for the Computer itself. Start it best-effort;
# if it cannot be bridged to Windows, the desktop remains fully usable and
# browser automation may use its existing fallback path.
if command -v google-chrome >/dev/null 2>&1; then
  nohup env \
    -u WAYLAND_DISPLAY -u WAYLAND_SOCKET \
    DISPLAY=127.0.0.1:1 \
    XDG_SESSION_TYPE=x11 GDK_BACKEND=x11 \
    google-chrome \
    --ozone-platform=x11 \
    --user-data-dir="$HOME/.agentie-chrome" \
    --remote-debugging-port=9222 \
    --remote-debugging-address=127.0.0.1 \
    --remote-allow-origins=* \
    --no-first-run --no-default-browser-check --disable-gpu \
    about:blank >/tmp/agentie-chrome.log 2>&1 </dev/null &

  for i in $(seq 1 30); do
    (echo >/dev/tcp/127.0.0.1/9222) >/dev/null 2>&1 && break
    sleep 0.1
  done
  if [ -n "$WSL_IP" ] && command -v socat >/dev/null 2>&1 && (echo >/dev/tcp/127.0.0.1/9222) >/dev/null 2>&1; then
    nohup socat TCP-LISTEN:9222,bind="$WSL_IP",reuseaddr,fork TCP:127.0.0.1:9222 >/tmp/agentie-cdp-bridge.log 2>&1 </dev/null &
  fi
fi

# The Computer is ready as soon as its visual desktop bridge is available.
for i in $(seq 1 120); do
  (echo >/dev/tcp/127.0.0.1/6080) >/dev/null 2>&1 && { echo '__DESKTOP_READY__'; exit 0; }
  sleep 0.2
done

echo '__START_TIMEOUT__'
echo '--- VNC ---'; cat /tmp/agentie-vnc.log 2>/dev/null || true
echo '--- XFCE ---'; cat /tmp/agentie-xfce.log 2>/dev/null || true
echo '--- noVNC ---'; cat /tmp/agentie-novnc.log 2>/dev/null || true
exit 56
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
        return {**status(), "setup_required": True, "message": "A required desktop component is still missing inside Ubuntu.", "setup_command": "sudo apt-get install -y xfce4 xfce4-terminal thunar tigervnc-standalone-server novnc websockify dbus-x11", "details": output[-1000:]}
    if proc.returncode != 0:
        raise RuntimeError("Could not start the Agentie WSL desktop: " + (output[-3000:] or f"exit {proc.returncode}"))
    for _ in range(60):
        current = status()
        if current["novnc_ready"]:
            return {**current, "message": "Agentie Computer desktop started."}
        time.sleep(0.25)
    return status()


def ensure_started() -> dict[str, Any]:
    with _START_LOCK:
        current = status()
        if current["novnc_ready"]:
            return {**current, "message": "Agentie Computer is ready."}

        first = _start_once()
        if first.get("novnc_ready"):
            return first
        if first.get("setup_required"):
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
        raise RuntimeError(
            "Agentie started the Linux desktop services, but Windows cannot reach the visual desktop on port 6080. "
            f"WSL IP={current.get('wsl_ip') or 'unknown'}."
        )


def stop() -> dict[str, Any]:
    if not _windows_wsl():
        return {**status(), "message": "Agentie Computer is already stopped."}
    script = r'''
pkill -f 'websockify.*6080' >/dev/null 2>&1 || true
pkill -f 'socat.*9222' >/dev/null 2>&1 || true
pkill -f 'google-chrome.*\.agentie-chrome' >/dev/null 2>&1 || true
pkill -f 'Xtigervnc.*:1' >/dev/null 2>&1 || true
pkill -f 'AGENTIE_DESKTOP=1.*startxfce4' >/dev/null 2>&1 || true
'''
    try:
        _run_wsl(script, timeout=12)
        _prepare_x11_runtime()
    except Exception:
        pass
    return {**status(), "running": False, "novnc_ready": False, "chrome_ready": False, "novnc_url": None, "cdp_url": None, "message": "Agentie Computer stopped."}
