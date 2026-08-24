from __future__ import annotations

import threading
import time

from agentie.core import company_computer_backend as computer

_THREAD: threading.Thread | None = None
_STOP = threading.Event()
_LOCK = threading.Lock()


def _idle_seconds() -> int:
    return max(60, int(computer.IDLE_SECONDS))


def run_idle_cycle(now: float | None = None) -> str | None:
    """Run one deterministic Company Computer idle lifecycle check.

    USER_CONTROL and USER_REQUIRED are never reclaimed automatically. A stale
    AGENT_CONTROL lease is released only after the configured idle threshold,
    then the VM is suspended so the selected hypervisor releases host resources
    while the guest disk remains persistent.
    """
    current = computer._row()
    state = str(current.get("state") or "STOPPED")
    if state in {"STOPPED", "STARTING", "SUSPENDED", "ERROR", "USER_CONTROL", "USER_REQUIRED"}:
        return None
    instant = float(now if now is not None else time.time())
    last = float(current.get("last_activity") or instant)
    if instant - last < _idle_seconds():
        return None
    if state == "AGENT_CONTROL":
        # Do not pass an agent id here: this is the central lease reaper and the
        # threshold itself is the proof that the lease has gone inactive.
        computer.release_control()
        state = "IDLE"
    if state in {"READY", "IDLE"}:
        computer.suspend()
        return "suspended"
    return None


def start_idle_coordinator() -> None:
    global _THREAD
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return
        _STOP.clear()

        def worker() -> None:
            while not _STOP.wait(15):
                try:
                    run_idle_cycle()
                except Exception:
                    # Lifecycle checks must never crash Agentie. Runtime status
                    # exposes actual backend errors to the Computer card instead.
                    continue

        _THREAD = threading.Thread(
            target=worker,
            name="agentie-company-computer-idle-coordinator",
            daemon=True,
        )
        _THREAD.start()


def stop_idle_coordinator() -> None:
    _STOP.set()
