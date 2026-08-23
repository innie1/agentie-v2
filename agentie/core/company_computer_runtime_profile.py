from __future__ import annotations

"""Apply Company Computer VM hardware-profile migrations safely.

QEMU device choices are fixed when a VM process launches.  Reusing a live QEMU
process after Agentie updates its hardware arguments (for example virtio-vga to
standard VGA on WHPX) leaves the guest on the old hardware even though the new
code is present.  This wrapper performs a one-time process relaunch while
preserving the persistent QCOW2 disk and guest data.
"""

from pathlib import Path
from typing import Any

from agentie.core import company_computer as computer

_PROFILE_VERSION = "2026-08-whpx-standard-vga-v1"
_PROFILE_FILE = computer.ROOT / "runtime-profile.version"
_ORIGINAL_START = computer.start


def _profile_is_current() -> bool:
    try:
        return _PROFILE_FILE.read_text(encoding="utf-8").strip() == _PROFILE_VERSION
    except Exception:
        return False


def _mark_profile_current() -> None:
    _PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PROFILE_FILE.write_text(_PROFILE_VERSION + "\n", encoding="utf-8")


def _live_runtime_needs_relaunch() -> bool:
    row = computer._row()
    return (
        computer._is_pid_alive(row.get("vm_pid"))
        and computer._port_open(computer.VNC_PORT)
        and not _profile_is_current()
    )


def start() -> dict[str, Any]:
    """Start using the current hardware profile, relaunching stale live QEMU once."""
    row = computer._row()
    if _live_runtime_needs_relaunch():
        if row.get("state") in {"AGENT_CONTROL", "USER_CONTROL", "USER_REQUIRED"}:
            raise computer.ComputerError(
                "Agentie Computer needs a one-time runtime update before it can continue. "
                "Release Computer control and start it again."
            )

        # A paused VM cannot process ACPI powerdown. Resume it before asking the
        # normal stop path to shut down gracefully. If QMP resume itself fails,
        # stop() still has a terminate fallback and never deletes the QCOW2 disk.
        if row.get("state") == "SUSPENDED" and computer._is_pid_alive(row.get("vm_pid")):
            try:
                computer._qmp_command("cont")
                computer._update(state="IDLE", last_activity=computer._now())
            except Exception:
                pass

        computer.stop()

    result = _ORIGINAL_START()
    _mark_profile_current()
    return result


computer.start = start
