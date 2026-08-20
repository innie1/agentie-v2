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
    script = "DEBIAN_FRONTEND=noninteractive apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y tigervnc-standalone-server tigervnc-tools novnc websockify xfce4 dbus-x11 socat"
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
'''
    proc = _run_wsl(script, timeout=12)
    if proc.returncode != 0:
        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        raise RuntimeError("Could not clear stale Agentie display state: " + (output[-1000:] or f"exit {proc.returncode}"))


def _start_script() -> str:
    return r'''
set -u
missing=""
command -v Xtigervnc >/dev/null 2>&1 || missing="$missing Xtigervnc"
command -v websockify >/dev/null 2>&1 || missing="$missing websockify"
[ -d /usr/share/novnc ] || missing="$missing novnc"
command -v startxfce4 >/dev/null 2>&1 || missing="$missing xfce4"
command -v dbus-launch >/dev/null 2>&1 || missing="$missing dbus-x11"
command -v google-chrome >/dev/null 2>&1 || missing="$missing google-chrome"
command -v socat >/dev/null 2>&1 || missing="$missing socat"
if [ -n "$missing" ]; then echo "__MISSING__:$missing"; exit 42; fi

WSL_IP="$(hostname -I | awk '{print $1}')"
if [ -z "$WSL_IP" ]; then echo '__NO_WSL_IP__'; exit 57; fi

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

# Chrome stays on Ubuntu loopback. Some Chrome builds ignore a requested
# non-loopback DevTools bind. socat exposes only the WSL-IP side of 9222.
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

for i in $(seq 1 80); do
  (echo >/dev/tcp/127.0.0.1/9222) >/dev/null 2>&1 && break
  sleep 0.1
done
if ! (echo >/dev/tcp/127.0.0.1/9222) >/dev/null 2>&1; then
  echo '__CHROME_ERROR__'; cat /tmp/agentie-chrome.log 2>/dev/null || true; exit 58
fi

nohup socat TCP-LISTEN:9222,bind="$WSL_IP",reuseaddr,fork TCP:127.0.0.1:9222 >/tmp/agentie-cdp-bridge.log 2>&1 </dev/null &

for i in $(seq 1 120); do
  novnc_ok=0; cdp_ok=0
  (echo >/dev/tcp/127.0.0.1/6080) >/dev/null 2>&1 && novnc_ok=1
  (echo >/dev/tcp/"$WSL_IP"/9222) >/dev/null 2>&1 && cdp_ok=1
  if [ "$novnc_ok" = 1 ] && [ "$cdp_ok" = 1 ]; then echo "__READY__:$WSL_IP"; exit 0; fi
  sleep 0.2
done

echo '__START_TIMEOUT__'
echo '--- VNC ---'; cat /tmp/agentie-vnc.log 2>/dev/null || true
echo '--- XFCE ---'; cat /tmp/agentie-xfce.log 2>/dev/null || true
echo '--- noVNC ---'; cat /tmp/agentie-novnc.log 2>/dev/null || true
echo '--- Chrome ---'; cat /tmp/agentie-chrome.log 2>/dev/null || true
echo '--- CDP bridge ---'; cat /tmp/agentie-cdp-bridge.log 2>/dev/null || true
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
        return {**status(), "setup_required": True, "message": "Google Chrome or a required desktop component is still missing inside Ubuntu.", "setup_command": "google-chrome --version", "details": output[-1000:]}
    if proc.returncode != 0:
        raise RuntimeError("Could not start the Agentie WSL desktop: " + (output[-3000:] or f"exit {proc.returncode}"))
    for _ in range(60):
        current = status()
        if current["novnc_ready"] and current["chrome_ready"]:
            return {**current, "message": f"Agentie Computer started. noVNC={current.get('novnc_host')}, CDP={current.get('cdp_host')}."}
        time.sleep(0.25)
    return status()


def ensure_started() -> dict[str, Any]:
    with _START_LOCK:
        current = status()
        if current["novnc_ready"] and current["chrome_ready"]:
            return {**current, "message": "Agentie Computer is ready."}

        first = _start_once()
        if first.get("novnc_ready") and first.get("chrome_ready"):
            return first
        if first.get("setup_required"):
            return first

        changed = _ensure_mirrored_networking()
        if changed:
            _shutdown_wsl()
            second = _start_once()
            if second.get("novnc_ready") and second.get("chrome_ready"):
                return {**second, "message": "Agentie Computer started after enabling WSL mirrored networking."}
            if second.get("setup_required"):
                return second

        current = status()
        raise RuntimeError(
            "Agentie started the Linux desktop, but the Windows bridge is incomplete. "
            f"noVNC host={current.get('novnc_host') or 'unreachable'}, "
            f"Chrome CDP host={current.get('cdp_host') or 'unreachable'}, "
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
