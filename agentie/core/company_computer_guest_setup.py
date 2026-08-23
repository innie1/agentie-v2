from __future__ import annotations

import base64
import time
from typing import Any

from agentie.core import company_computer as computer
from agentie.core import company_computer_windows_accel as _windows_accel  # registers Windows acceleration fix
from agentie.core import company_computer_whpx as _whpx_compat  # removes WHPX-incompatible CPU/APIC settings
from agentie.core import company_computer_guest_agent as _guest_agent  # registers QGA API on computer

_SETUP_MARKER = "/var/lib/agentie/runtime-v3"


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
    return " | ".join(chunks)[-1800:]


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
        # QGA is already alive. A cloud-init wait timeout should not permanently
        # brick the persistent VM; the repair script below also waits for package
        # manager processes and repairs interrupted dpkg state.
        if "timed out" not in str(exc).lower():
            raise


def _marker_exists() -> bool:
    try:
        result = computer.guest_exec(["/usr/bin/test", "-f", _SETUP_MARKER], timeout=15)
        return int(result.get("exitcode") or 0) == 0
    except Exception:
        return False


def _repair_script() -> str:
    return r"""
set -eu
export DEBIAN_FRONTEND=noninteractive

# QGA can become reachable before cloud-init has completely released apt/dpkg.
# Wait for any first-boot package manager work before repairing the guest.
for _i in $(seq 1 150); do
  if ! pgrep -x apt-get >/dev/null 2>&1 && ! pgrep -x apt >/dev/null 2>&1 && ! pgrep -x dpkg >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

dpkg --configure -a
apt-get update
apt-get install -y --no-install-recommends xserver-xorg-legacy xdotool
mkdir -p /etc/X11 /var/lib/agentie /tmp/runtime-agentie /home/agentie/Downloads /home/agentie/Desktop
cat >/etc/X11/Xwrapper.config <<'EOF'
allowed_users=anybody
needs_root_rights=yes
EOF
chmod 0644 /etc/X11/Xwrapper.config

# Recreate the desktop bootstrap files on every repair pass. Persistent disks
# created by an older/broken first boot may have the packages installed while
# the service file or xinit script is missing.
cat >/home/agentie/.xinitrc <<'EOF'
#!/bin/sh
export DISPLAY=:0
export XDG_RUNTIME_DIR=/tmp/runtime-agentie
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
dbus-launch --exit-with-session sh -c '
  pcmanfm --desktop --profile LXDE >/tmp/pcmanfm.log 2>&1 &
  chromium --user-data-dir=/home/agentie/.config/chromium-agentie --remote-debugging-port=9222 --remote-debugging-address=0.0.0.0 --remote-allow-origins=* --no-first-run --no-default-browser-check --restore-last-session about:blank >/tmp/chromium.log 2>&1 &
  exec openbox-session
'
EOF
chmod 0755 /home/agentie/.xinitrc

cat >/etc/systemd/system/agentie-desktop.service <<'EOF'
[Unit]
Description=Agentie lightweight desktop
After=network-online.target cloud-final.service
Wants=network-online.target

[Service]
User=agentie
Environment=HOME=/home/agentie
WorkingDirectory=/home/agentie
TTYPath=/dev/tty1
StandardInput=tty-force
TTYReset=yes
TTYVHangup=yes
ExecStart=/usr/bin/startx /home/agentie/.xinitrc -- :0 -nolisten tcp vt1
Restart=always
RestartSec=2

[Install]
WantedBy=graphical.target
EOF

chown -R agentie:agentie /home/agentie
chown agentie:agentie /tmp/runtime-agentie
chmod 0700 /tmp/runtime-agentie
# QEMU Guest Agent is Agentie's privileged maintenance channel. The interactive
# desktop user must not retain cloud-image passwordless sudo that could bypass
# Agentie's approval layer.
if command -v gpasswd >/dev/null 2>&1; then gpasswd -d agentie sudo >/dev/null 2>&1 || true; fi
if [ -d /etc/sudoers.d ]; then
  for f in /etc/sudoers.d/*; do
    [ -f "$f" ] || continue
    sed -i '/^[[:space:]]*agentie[[:space:]]/d' "$f" || true
  done
fi
# Ensure startx can own a guest virtual terminal when launched from systemd.
mkdir -p /etc/systemd/system/agentie-desktop.service.d
cat >/etc/systemd/system/agentie-desktop.service.d/10-agentie-runtime.conf <<'EOF'
[Service]
TTYPath=/dev/tty1
StandardInput=tty-force
TTYReset=yes
TTYVHangup=yes
EOF
systemctl daemon-reload
systemctl enable qemu-guest-agent >/dev/null 2>&1 || true
# Do not restart qemu-guest-agent from a command currently travelling through
# that same QGA channel. The active service is already what made this setup
# request possible.
systemctl enable agentie-desktop.service
systemctl restart agentie-desktop.service
sleep 2
systemctl is-active --quiet agentie-desktop.service
touch /var/lib/agentie/runtime-v3
""".strip()


def ensure_guest_runtime(*, timeout: int = 300) -> dict[str, Any]:
    """Make first-use guest prerequisites reliable without manual host commands.

    The persistent guest is upgraded in place. This does not recreate its
    QCOW2 disk, Chromium profile, files, applications, or login state.
    """
    computer.start()
    _wait_for_qga(timeout)
    _wait_for_cloud_init(timeout)
    if not _marker_exists():
        result = computer.guest_exec(["/bin/bash", "-lc", _repair_script()], timeout=max(300, timeout))
        if int(result.get("exitcode") or 0) != 0:
            detail = _guest_output(result)
            raise computer.ComputerError(
                "Could not finish Company Computer guest preparation."
                + (f" Details: {detail}" if detail else f" Guest exit code: {result.get('exitcode')}.")
            )
    else:
        active = computer.guest_exec(["/bin/systemctl", "is-active", "--quiet", "agentie-desktop.service"], timeout=20)
        if int(active.get("exitcode") or 0) != 0:
            restart = computer.guest_exec(["/bin/systemctl", "restart", "agentie-desktop.service"], timeout=60)
            if int(restart.get("exitcode") or 0) != 0:
                detail = _guest_output(restart)
                raise computer.ComputerError(
                    "Company Computer desktop service could not be restarted."
                    + (f" Details: {detail}" if detail else "")
                )
    computer.touch_activity()
    return computer.status()
