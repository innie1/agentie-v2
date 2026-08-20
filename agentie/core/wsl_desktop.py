from __future__ import annotations

import os
import shutil
import socket
import subprocess
import urllib.request
from typing import Any

DISTRO = os.getenv("AGENTIE_WSL_DISTRO", "Ubuntu")
NOVNC_URL = "http://127.0.0.1:6080/vnc_lite.html?autoconnect=1&resize=scale&reconnect=1&path=websockify"
CDP_URL = "http://127.0.0.1:9222"


def _windows_wsl() -> str | None:
    return shutil.which("wsl.exe") or shutil.which("wsl") if os.name == "nt" else None


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


def _run_wsl(script: str, timeout: int = 25) -> subprocess.CompletedProcess[str]:
    executable = _windows_wsl()
    if not executable:
        raise RuntimeError("The real Agentie Computer requires Windows with WSL2.")
    return subprocess.run(
        [executable, "-d", DISTRO, "--", "bash", "-lc", script],
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )


def ensure_started() -> dict[str, Any]:
    current = status()
    if current["novnc_ready"] and current["chrome_ready"]:
        return {**current, "message": "Agentie Computer is ready."}

    script = r'''
set -e
missing=""
command -v tigervncserver >/dev/null 2>&1 || missing="$missing tigervncserver"
command -v websockify >/dev/null 2>&1 || missing="$missing websockify"
[ -d /usr/share/novnc ] || missing="$missing novnc"
command -v startxfce4 >/dev/null 2>&1 || missing="$missing xfce4"
command -v google-chrome >/dev/null 2>&1 || missing="$missing google-chrome"
if [ -n "$missing" ]; then
  echo "__MISSING__:$missing"
  exit 42
fi
mkdir -p "$HOME/.vnc"
cat > "$HOME/.vnc/xstartup" <<'EOF'
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
startxfce4 &
EOF
chmod +x "$HOME/.vnc/xstartup"
if ! pgrep -f 'Xtigervnc.*:1' >/dev/null 2>&1; then
  tigervncserver :1 -geometry 1440x900 -depth 24 -localhost yes -SecurityTypes None >/tmp/agentie-vnc-start.log 2>&1
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
    about:blank >/tmp/agentie-chrome.log 2>&1 </dev/null &
fi
for i in $(seq 1 40); do
  if (echo >/dev/tcp/127.0.0.1/6080) >/dev/null 2>&1 && (echo >/dev/tcp/127.0.0.1/9222) >/dev/null 2>&1; then
    echo '__READY__'
    exit 0
  fi
  sleep 0.25
done
echo '__STARTED__'
'''
    try:
        proc = _run_wsl(script, timeout=30)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("The Agentie Computer took too long to start.") from exc

    output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if proc.returncode == 42 or "__MISSING__" in output:
        return {
            **status(),
            "setup_required": True,
            "message": "One-time WSL desktop packages are still required.",
            "setup_command": "sudo apt update && sudo apt install -y tigervnc-standalone-server tigervnc-tools novnc websockify",
            "details": output[-1000:],
        }
    if proc.returncode != 0:
        raise RuntimeError("Could not start the Agentie WSL desktop: " + (output[-1200:] or f"exit {proc.returncode}"))

    # WSL localhost forwarding can take a moment to become visible to Windows.
    for _ in range(30):
        current = status()
        if current["novnc_ready"]:
            return {**current, "message": "Agentie Computer started."}
        import time
        time.sleep(0.2)
    return {**status(), "message": "The WSL desktop started, but its local display bridge is not reachable yet."}


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
    except Exception:
        pass
    return {**status(), "running": False, "novnc_ready": False, "chrome_ready": False, "novnc_url": None, "cdp_url": None, "message": "Agentie Computer stopped."}
