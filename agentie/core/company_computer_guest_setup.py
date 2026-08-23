from __future__ import annotations

import base64
import time
from typing import Any

from agentie.core import company_computer as computer
from agentie.core import company_computer_windows_accel as _windows_accel  # registers Windows acceleration fix
from agentie.core import company_computer_whpx as _whpx_compat  # removes WHPX-incompatible CPU/APIC settings
from agentie.core import company_computer_guest_agent as _guest_agent  # registers QGA API on computer

_SETUP_MARKER = "/var/lib/agentie/runtime-v6"


def _wait_for_qga(timeout: int = 300) -> None:
    deadline = time.time() + max(30, int(timeout))
    last_error = ""
    while time.time() < deadline:
        try:
            result = computer.guest_exec(["/bin/true"], timeout=8)
            if int(result.get("exitcode") or 0) == 0:
                return
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1)
    raise computer.ComputerError(
        "Agentie Computer started, but its guest automation service did not become ready."
        + (f" Details: {last_error[-400:]}" if last_error else "")
    )


def _guest_output(result: dict[str, Any]) -> str:
    """Decode QGA guest-exec stdout/stderr for actionable setup errors."""
    chunks: list[str] = []
    for key, label in (("out-data", "stdout"), ("err-data", "stderr")):
        raw = result.get(key)
        if not raw:
            continue
        try:
            text = base64.b64decode(str(raw)).decode("utf-8", "replace").strip()
        except Exception:
            text = str(raw).strip()
        if text:
            chunks.append(f"{label}: {text}")
    return " | ".join(chunks)[-5000:]


def _wait_for_cloud_init(timeout: int = 300) -> None:
    """Let Debian finish first-boot package work before Agentie's repair pass."""
    command = (
        "if command -v cloud-init >/dev/null 2>&1; then "
        "cloud-init status --wait >/tmp/agentie-cloud-init-status.txt 2>&1 || true; "
        "fi; exit 0"
    )
    try:
        computer.guest_exec(["/bin/bash", "-lc", command], timeout=max(60, int(timeout)))
    except computer.ComputerError as exc:
        if "timed out" not in str(exc).lower():
            raise


def _marker_exists() -> bool:
    try:
        result = computer.guest_exec(["/usr/bin/test", "-f", _SETUP_MARKER], timeout=15)
        return int(result.get("exitcode") or 0) == 0
    except Exception:
        return False


def _desktop_health_command() -> list[str]:
    return [
        "/bin/bash",
        "-lc",
        "systemctl is-active --quiet agentie-xorg.service && "
        "systemctl is-active --quiet agentie-desktop.service && "
        "DISPLAY=:0 /usr/bin/xdotool getdisplaygeometry >/dev/null 2>&1",
    ]


def _desktop_diagnostics_command() -> list[str]:
    return [
        "/bin/bash",
        "-lc",
        "echo '--- agentie-xorg.service ---'; "
        "systemctl status agentie-xorg.service --no-pager -l || true; "
        "echo '--- agentie-desktop.service ---'; "
        "systemctl status agentie-desktop.service --no-pager -l || true; "
        "echo '--- xorg journal ---'; "
        "journalctl -u agentie-xorg.service -n 60 --no-pager || true; "
        "echo '--- desktop journal ---'; "
        "journalctl -u agentie-desktop.service -n 60 --no-pager || true; "
        "echo '--- Xorg log ---'; "
        "tail -n 80 /var/log/Xorg.0.log 2>/dev/null || true; "
        "echo '--- Openbox log ---'; "
        "tail -n 80 /tmp/openbox.log 2>/dev/null || true; "
        "echo '--- PCManFM log ---'; "
        "tail -n 80 /tmp/pcmanfm.log 2>/dev/null || true; "
        "echo '--- Chromium log ---'; "
        "tail -n 80 /tmp/chromium.log 2>/dev/null || true",
    ]


def _repair_script() -> str:
    return r"""
set -eu
export DEBIAN_FRONTEND=noninteractive

for _i in $(seq 1 150); do
  if ! pgrep -x apt-get >/dev/null 2>&1 && ! pgrep -x apt >/dev/null 2>&1 && ! pgrep -x dpkg >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

dpkg --configure -a
apt-get update
apt-get install -y --no-install-recommends \
  xserver-xorg xserver-xorg-core xserver-xorg-video-all xserver-xorg-legacy \
  openbox dbus dbus-x11 pcmanfm xterm chromium qemu-guest-agent xdotool \
  curl ca-certificates unzip fonts-dejavu-core

mkdir -p /etc/X11 /var/lib/agentie /tmp/runtime-agentie /home/agentie/Downloads /home/agentie/Desktop
cat >/etc/X11/Xwrapper.config <<'EOF'
allowed_users=anybody
needs_root_rights=yes
EOF
chmod 0644 /etc/X11/Xwrapper.config

systemctl stop agentie-desktop.service >/dev/null 2>&1 || true
systemctl stop agentie-xorg.service >/dev/null 2>&1 || true
rm -rf /etc/systemd/system/agentie-desktop.service.d

cat >/home/agentie/.agentie-desktop-session.sh <<'EOF'
#!/bin/bash
set -eu
export DISPLAY=:0
export HOME=/home/agentie
export XDG_RUNTIME_DIR=/tmp/runtime-agentie
mkdir -p "$XDG_RUNTIME_DIR"
chmod 0700 "$XDG_RUNTIME_DIR"
# The X11 socket can exist before Xorg is ready to accept clients. Wait until a
# real X11 client can query the display before launching Openbox or Chromium.
for _i in $(seq 1 120); do
  if DISPLAY=:0 /usr/bin/xdotool getdisplaygeometry >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
DISPLAY=:0 /usr/bin/xdotool getdisplaygeometry >/dev/null 2>&1 || exit 1
exec /usr/bin/dbus-run-session -- /bin/sh -lc '
  pcmanfm --desktop --profile LXDE >/tmp/pcmanfm.log 2>&1 &
  chromium --user-data-dir=/home/agentie/.config/chromium-agentie --remote-debugging-port=9222 --remote-debugging-address=0.0.0.0 --remote-allow-origins=* --no-first-run --no-default-browser-check --restore-last-session about:blank >/tmp/chromium.log 2>&1 &
  exec /usr/bin/openbox --sm-disable >/tmp/openbox.log 2>&1
'
EOF
chmod 0755 /home/agentie/.agentie-desktop-session.sh
chown agentie:agentie /home/agentie/.agentie-desktop-session.sh

cat >/etc/systemd/system/agentie-xorg.service <<'EOF'
[Unit]
Description=Agentie Xorg display server
After=systemd-user-sessions.service

[Service]
Type=simple
ExecStart=/usr/bin/Xorg :0 -noreset -nolisten tcp -ac vt1
Restart=always
RestartSec=2
TTYPath=/dev/tty1
StandardInput=tty-force
TTYReset=yes
TTYVHangup=yes

[Install]
WantedBy=graphical.target
EOF

cat >/etc/systemd/system/agentie-desktop.service <<'EOF'
[Unit]
Description=Agentie lightweight desktop session
Requires=agentie-xorg.service
After=agentie-xorg.service network-online.target
Wants=network-online.target

[Service]
Type=simple
User=agentie
Environment=HOME=/home/agentie
Environment=DISPLAY=:0
Environment=XDG_RUNTIME_DIR=/tmp/runtime-agentie
WorkingDirectory=/home/agentie
ExecStart=/home/agentie/.agentie-desktop-session.sh
Restart=on-failure
RestartSec=2

[Install]
WantedBy=graphical.target
EOF

chown -R agentie:agentie /home/agentie
chown agentie:agentie /tmp/runtime-agentie
chmod 0700 /tmp/runtime-agentie

if command -v gpasswd >/dev/null 2>&1; then gpasswd -d agentie sudo >/dev/null 2>&1 || true; fi
if [ -d /etc/sudoers.d ]; then
  for f in /etc/sudoers.d/*; do
    [ -f "$f" ] || continue
    sed -i '/^[[:space:]]*agentie[[:space:]]/d' "$f" || true
  done
fi

systemctl daemon-reload
systemctl reset-failed agentie-xorg.service agentie-desktop.service >/dev/null 2>&1 || true
systemctl enable qemu-guest-agent >/dev/null 2>&1 || true
systemctl enable agentie-xorg.service agentie-desktop.service
systemctl restart agentie-xorg.service

# Do not rely on the Unix socket alone: Xorg creates it before initialization is
# necessarily complete. Require a successful X11 query before starting desktop.
for _i in $(seq 1 120); do
  if DISPLAY=:0 /usr/bin/xdotool getdisplaygeometry >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
if ! DISPLAY=:0 /usr/bin/xdotool getdisplaygeometry >/dev/null 2>&1; then
  echo '--- agentie-xorg.service status ---' >&2
  systemctl status agentie-xorg.service --no-pager -l >&2 || true
  echo '--- agentie-xorg.service journal ---' >&2
  journalctl -u agentie-xorg.service -n 80 --no-pager >&2 || true
  echo '--- Xorg log ---' >&2
  tail -n 100 /var/log/Xorg.0.log >&2 2>/dev/null || true
  exit 1
fi

systemctl restart agentie-desktop.service
sleep 4
if ! systemctl is-active --quiet agentie-xorg.service || ! systemctl is-active --quiet agentie-desktop.service || ! DISPLAY=:0 /usr/bin/xdotool getdisplaygeometry >/dev/null 2>&1; then
  echo '--- agentie-xorg.service status ---' >&2
  systemctl status agentie-xorg.service --no-pager -l >&2 || true
  echo '--- agentie-desktop.service status ---' >&2
  systemctl status agentie-desktop.service --no-pager -l >&2 || true
  echo '--- Xorg log ---' >&2
  tail -n 100 /var/log/Xorg.0.log >&2 2>/dev/null || true
  echo '--- desktop journal ---' >&2
  journalctl -u agentie-desktop.service -n 80 --no-pager >&2 || true
  echo '--- Openbox log ---' >&2
  tail -n 80 /tmp/openbox.log >&2 2>/dev/null || true
  echo '--- PCManFM log ---' >&2
  tail -n 80 /tmp/pcmanfm.log >&2 2>/dev/null || true
  echo '--- Chromium log ---' >&2
  tail -n 80 /tmp/chromium.log >&2 2>/dev/null || true
  exit 1
fi

touch /var/lib/agentie/runtime-v6
""".strip()


def _run_repair(timeout: int) -> None:
    result = computer.guest_exec(["/bin/bash", "-lc", _repair_script()], timeout=max(300, timeout))
    if int(result.get("exitcode") or 0) != 0:
        detail = _guest_output(result)
        raise computer.ComputerError(
            "Could not finish Company Computer guest preparation."
            + (f" Details: {detail}" if detail else f" Guest exit code: {result.get('exitcode')}.")
        )


def ensure_guest_runtime(*, timeout: int = 300) -> dict[str, Any]:
    """Make first-use guest prerequisites reliable without recreating its disk."""
    current = computer.status()
    if current.get("state") == "SUSPENDED":
        computer.resume()
    else:
        computer.start()
    _wait_for_qga(timeout)
    _wait_for_cloud_init(timeout)

    if not _marker_exists():
        _run_repair(timeout)
    else:
        health = computer.guest_exec(_desktop_health_command(), timeout=20)
        if int(health.get("exitcode") or 0) != 0:
            _run_repair(timeout)

    health = computer.guest_exec(_desktop_health_command(), timeout=20)
    if int(health.get("exitcode") or 0) != 0:
        diagnostics = computer.guest_exec(_desktop_diagnostics_command(), timeout=30)
        detail = _guest_output(diagnostics)
        raise computer.ComputerError(
            "Company Computer desktop services are not healthy."
            + (f" Details: {detail}" if detail else "")
        )

    computer.touch_activity()
    return computer.status()
