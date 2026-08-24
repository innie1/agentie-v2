from __future__ import annotations

"""Stable Company Computer backend facade.

Windows defaults to VirtualBox. macOS/Linux keep the existing QEMU backend.
Callers import this module instead of binding themselves to one hypervisor.
"""

import os
import platform
from types import ModuleType
from typing import Any

from agentie.core.company_computer import ComputerError, IDLE_SECONDS


def backend_name(system: str | None = None) -> str:
    override = os.getenv("AGENTIE_COMPUTER_BACKEND", "").strip().lower()
    aliases = {
        "virtualbox": "virtualbox", "vbox": "virtualbox",
        "qemu": "qemu", "qemu_hvf": "qemu", "qemu_kvm": "qemu", "qemu_whpx": "qemu",
    }
    if override:
        if override not in aliases:
            raise ComputerError("AGENTIE_COMPUTER_BACKEND must be virtualbox or qemu.")
        return aliases[override]
    current = str(system or platform.system()).strip().lower()
    return "virtualbox" if current == "windows" else "qemu"


def _backend() -> ModuleType:
    if backend_name() == "virtualbox":
        from agentie.core import company_computer_virtualbox as backend
        return backend
    from agentie.core import company_computer as backend
    # QGA methods are registered on the QEMU module by this compatibility module.
    from agentie.core import company_computer_guest_agent as _guest_agent  # noqa: F401
    return backend


def selected_backend() -> str:
    return backend_name()


def _call(name: str, *args: Any, **kwargs: Any) -> Any:
    fn = getattr(_backend(), name, None)
    if not callable(fn):
        raise ComputerError(f"The selected Company Computer backend does not implement {name}.")
    return fn(*args, **kwargs)


def start() -> dict[str, Any]: return _call("start")
def stop() -> dict[str, Any]: return _call("stop")
def suspend() -> dict[str, Any]: return _call("suspend")
def resume() -> dict[str, Any]: return _call("resume")
def status() -> dict[str, Any]:
    result = dict(_call("status")); result.setdefault("backend", selected_backend()); return result

def prepare() -> dict[str, Any]: return _call("prepare")
def acquire_agent(agent_id: str, job_id: str | None = None) -> dict[str, Any]: return _call("acquire_agent", agent_id, job_id)
def acquire_for_session(session_id: str | None = None, job_id: str | None = None) -> dict[str, Any]: return _call("acquire_for_session", session_id, job_id)
def handoff_agent(from_agent_id: str, to_agent_id: str, job_id: str | None = None) -> dict[str, Any]: return _call("handoff_agent", from_agent_id, to_agent_id, job_id)
def request_user_takeover(agent_id: str, reason: str) -> dict[str, Any]: return _call("request_user_takeover", agent_id, reason)
def request_user_takeover_for_session(session_id: str | None, reason: str) -> dict[str, Any]: return _call("request_user_takeover_for_session", session_id, reason)
def acquire_user() -> dict[str, Any]: return _call("acquire_user")
def continue_agent() -> dict[str, Any]: return _call("continue_agent")
def release_control(agent_id: str | None = None) -> dict[str, Any]: return _call("release_control", agent_id)
def touch_activity(browser_state: dict[str, Any] | None = None) -> dict[str, Any]: return _call("touch_activity", browser_state)
def display_url(*, view_only: bool = False) -> str: return _call("display_url", view_only=view_only)
def guest_exec(command: list[str], timeout: int = 30) -> dict[str, Any]: return _call("guest_exec", command, timeout=timeout)
def _row() -> dict[str, Any]: return _call("_row")
def _session_agent_id(session_id: str | None) -> str: return _call("_session_agent_id", session_id)
