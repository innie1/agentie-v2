from __future__ import annotations

"""Lifecycle compatibility for resuming the persistent Company Computer.

QEMU keeps its host-side VNC/QMP/QGA sockets open while the virtual CPUs are
paused with QMP ``stop``.  The original ``company_computer.start()`` therefore
mistook a suspended VM for an already-running VM because the QEMU PID and VNC
socket were still alive.  Callers then waited for QGA forever while the guest
CPU remained paused.

Patch ``start()`` once so every normal Company Computer entry point treats a
live SUSPENDED VM as a resume operation and sends QMP ``cont`` first.
"""

from typing import Any

from agentie.core import company_computer as computer

_ORIGINAL_START = computer.start


def start() -> dict[str, Any]:
    with computer._STATE_LOCK:
        row = computer._row()
        pid = row.get("vm_pid")
        if row.get("state") == "SUSPENDED" and computer._is_pid_alive(pid):
            try:
                result = computer._qmp_command("cont")
                if result.get("error"):
                    raise computer.ComputerError(str(result["error"]))
            except Exception as exc:
                raise computer.ComputerError(
                    f"Could not resume suspended Agentie Computer: {exc}"
                ) from exc

            computer._update(
                state="IDLE",
                suspended_snapshot=0,
                last_activity=computer._now(),
                last_error=None,
            )
            computer._start_display_server()
            computer.start_idle_monitor()
            return computer.status()

    return _ORIGINAL_START()


computer.start = start
