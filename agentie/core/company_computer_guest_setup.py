from __future__ import annotations

import time
from typing import Any

from agentie.core import company_computer as computer
from agentie.core import company_computer_windows_accel as _windows_accel  # registers Windows acceleration fix
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
apt-get update
apt-get install -y --no-install-recommends xserver-xorg-legacy xdotool
mkdir -p /etc/X11 /var/lib/agentie /tmp/runtime-agentie /home/agentie/Downloads /home/agentie/Desktop
cat >/etc/X11/Xwrapper.config <<'EOF'
allowed_users=anybody
needs_root_rights=yes
EOF
chmod 0644 /etc/X11/Xwrapper.config
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
systemctl enable agentie-desktop.service >/dev/null 2>&1 || true
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
    if not _marker_exists():
        result = computer.guest_exec(["/bin/bash", "-lc", _repair_script()], timeout=max(300, timeout))
        if int(result.get("exitcode") or 0) != 0:
            raise computer.ComputerError("Could not finish Company Computer guest preparation.")
    else:
        active = computer.guest_exec(["/bin/systemctl", "is-active", "--quiet", "agentie-desktop.service"], timeout=20)
        if int(active.get("exitcode") or 0) != 0:
            restart = computer.guest_exec(["/bin/systemctl", "restart", "agentie-desktop.service"], timeout=60)
            if int(restart.get("exitcode") or 0) != 0:
                raise computer.ComputerError("Company Computer desktop service could not be restarted.")
    computer.touch_activity()
    return computer.status()
