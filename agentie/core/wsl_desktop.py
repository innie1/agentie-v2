from __future__ import annotations

import base64
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from typing import Any

DISTRO = os.getenv("AGENTIE_WSL_DISTRO", "Ubuntu")
NOVNC_URL = "http://127.0.0.1:6080/vnc_lite.html?autoconnect=1&resize=scale&reconnect=1&path=websockify"
CDP_URL = "http://127.0.0.1:9222"
_START_LOCK = threading.Lock()


def _windows_wsl() -> str | None:
    if os.name != "nt":
        return None
    return shutil.which("wsl.exe") or shutil.which("wsl")


def _port_open(port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_ready(url: str, timeout: float = 0.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= int(response.status) < 500
    except Exception:
        return False


def status() -> dict[str, Any]:
    supported = bool(_windows_wsl())
    novnc = _port_open(6080)
    cdp = _http_ready(CDP_URL + "/json/version")
    return {
        "supported": supported,
        "running": novnc,
        "novnc_ready": novnc,
        "chrome_ready": cdp,
        "novnc_url": NOVNC_URL if novnc else None,
        "cdp_url": CDP_URL if cdp else None,
        "distro": DISTRO,
    }


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


def _bootstrap_packages() -> None:
    script = "DEBIAN_FRONTEND=noninteractive apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y tigervnc-standalone-server tigervnc-tools novnc websockify xfce4 dbus-x11"
    try:
        proc = _run_wsl(script, timeout=300, root=True)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("The one-time Agentie desktop package installation timed out.") from exc
    if proc.returncode != 0:
        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        raise RuntimeError("Could not install the Agentie desktop bridge packages: " + (output[-1400:] or f"exit {proc.returncode}"))


def _prepare_x11_runtime() -> None:
    """Repair the shared X11 socket directory and stale display :1 state.

    /tmp/.X11-unix is a system-owned shared directory and must be mode 1777.
    VNC itself still runs as the normal Ubuntu user; root is used only for this
    filesystem preparation so a previous X server cannot poison future starts.
    """
    script = r'''
mkdir -p /tmp/.X11-unix
chown root:root /tmp/.X11-unix
chmod 1777 /tmp/.X11-unix
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1
'''
    proc = _run_wsl(script, timeout=12, root=True)
    if proc.returncode != 0:
        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        raise RuntimeError("Could not prepare the WSL X11 runtime: " + (output[-1000:] or f"exit {proc.returncode}"))


def _start_script() -> str:
    return r'''
set -u
missing=""
command -v tigervncserver >/dev/null 2>&1 || missing="$missing tigervncserver"
command -v websockify >/dev/null 2>&1 || missing="$missing websockify"
[ -d /usr/share/novnc ] || missing="$missing novnc"
command -v startxfce4 >/dev/null 2>&1 || missing="$missing xfce4"
command -v dbus-launch >/dev/null 2>&1 || missing="$missing dbus-x11"
command -v google-chrome >/dev/null 2>&1 || missing="$missing google-chrome"
if [ -n "$missing" ]; then
  echo "__MISSING__:$missing"
  exit 42
fi

mkdir -p "$HOME/.config/tigervnc"
cat > "$HOME/.config/tigervnc/xstartup" <<'EOF'
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
exec dbus-launch --exit-with-session startxfce4
EOF
chmod +x "$HOME/.config/tigervnc/xstartup"

# Stop only Agentie's own display before starting a fresh one. The root-only
# stale socket cleanup happens outside this script in _prepare_x11_runtime().
tigervncserver -kill :1 >/dev/null 2>&1 || true
tigervncserver -list -cleanstale >/dev/null 2>&1 || true

if ! pgrep -f 'Xtigervnc.*:1' >/dev/null 2>&1; then
  if ! tigervncserver :1 -geometry 1440x900 -depth 24 -localhost yes -SecurityTypes None -xstartup "$HOME/.config/tigervnc/xstartup" >/tmp/agentie-vnc-start.log 2>&1; then
    echo '__VNC_ERROR__'
    cat /tmp/agentie-vnc-start.log 2>/dev/null || true
    tail -n 80 "$HOME"/.config/tigervnc/*.log 2>/dev/null || true
    exit 55
  fi
fi

if ! pgrep -f 'websockify.*6080' >/dev/null 2>&1; then
  nohup websockify --web=/usr/share/novnc 127.0.0.1:6080 127.0.0.1:5901 >/tmp/agentie-novnc.log 2>&1 </dev/null &
fi

if ! pgrep -f 'google-chrome.*\.agentie-chrome' >/dev/null 2>&1; then
  nohup env DISPLAY=:1 google-chrome \
    --user-data-dir="$HOME/.agentie-chrome" \
    --remote-debugging-port=9222 \
    --remote-debugging-address=127.0.0.1 \
    --no-first-run --no-default-browser-check \
    --disable-gpu \
    about:blank >/tmp/agentie-chrome.log 2>&1 </dev/null &
fi

for i in $(seq 1 100); do
  novnc_ok=0
  chrome_ok=0
  (echo >/dev/tcp/127.0.0.1/6080) >/dev/null 2>&1 && novnc_ok=1
  (echo >/dev/tcp/127.0.0.1/9222) >/dev/null 2>&1 && chrome_ok=1
  if [ "$novnc_ok" = 1 ] && [ "$chrome_ok" = 1 ]; then
    echo '__READY__'
    exit 0
  fi
  sleep 0.2
done

echo '__START_TIMEOUT__'
echo '--- VNC ---'
cat /tmp/agentie-vnc-start.log 2>/dev/null || true
echo '--- noVNC ---'
cat /tmp/agentie-novnc.log 2>/dev/null || true
echo '--- Chrome ---'
cat /tmp/agentie-chrome.log 2>/dev/null || true
exit 56
'''


def ensure_started() -> dict[str, Any]:
    with _START_LOCK:
        current = status()
        if current["novnc_ready"] and current["chrome_ready"]:
            return {**current, "message": "Agentie Computer is ready."}

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
            return {
                **status(),
                "setup_required": True,
                "message": "Google Chrome or a required desktop component is still missing inside Ubuntu.",
                "setup_command": "google-chrome --version",
                "details": output[-1000:],
            }
        if proc.returncode != 0:
            detail = output[-2400:] or f"exit {proc.returncode}"
            raise RuntimeError("Could not start the Agentie WSL desktop: " + detail)

        for _ in range(50):
            current = status()
            if current["novnc_ready"] and current["chrome_ready"]:
                return {**current, "message": "Agentie Computer started."}
            time.sleep(0.2)
        raise RuntimeError("The WSL desktop process started, but noVNC or Chrome did not become reachable.")


def stop() -> dict[str, Any]:
    if not _windows_wsl():
        return {**status(), "message": "Agentie Computer is already stopped."}
    script = r'''
pkill -f 'websockify.*6080' >/dev/null 2>&1 || true
pkill -f 'google-chrome.*\.agentie-chrome' >/dev/null 2>&1 || true
tigervncserver -kill :1 >/dev/null 2>&1 || true
'''
    try:
        _run_wsl(script, timeout=12)
        _prepare_x11_runtime()
    except Exception:
        pass
    return {**status(), "running": False, "novnc_ready": False, "chrome_ready": False, "novnc_url": None, "cdp_url": None, "message": "Agentie Computer stopped."}
