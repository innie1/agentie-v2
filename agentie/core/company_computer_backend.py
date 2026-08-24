from __future__ import annotations

"""Stable Company Computer backend facade.

Windows defaults to VirtualBox. macOS/Linux keep the existing QEMU backend.
Callers import this module instead of binding themselves to one hypervisor.
"""

import base64
import os
import platform
from pathlib import Path
from types import ModuleType
from typing import Any

from agentie.core.company_computer import ComputerError
from agentie.core.company_computer import IDLE_SECONDS as IDLE_SECONDS


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
        from agentie.core import company_computer_virtualbox_provisioning as _vbox_provisioning  # noqa: F401
        from agentie.core import company_computer_virtualbox_guestcontrol as _vbox_guestcontrol  # noqa: F401
        from agentie.core import company_computer_virtualbox_recovery as _vbox_recovery  # noqa: F401
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


def _state_result(value: Any) -> Any:
    if isinstance(value, dict):
        value = dict(value)
        value.setdefault("backend", selected_backend())
    return value


def start() -> dict[str, Any]: return _state_result(_call("start"))
def stop() -> dict[str, Any]: return _state_result(_call("stop"))
def suspend() -> dict[str, Any]: return _state_result(_call("suspend"))
def resume() -> dict[str, Any]: return _state_result(_call("resume"))
def status() -> dict[str, Any]: return _state_result(_call("status"))
def prepare() -> dict[str, Any]: return _state_result(_call("prepare"))
def acquire_agent(agent_id: str, job_id: str | None = None) -> dict[str, Any]: return _state_result(_call("acquire_agent", agent_id, job_id))
def acquire_for_session(session_id: str | None = None, job_id: str | None = None) -> dict[str, Any]: return _state_result(_call("acquire_for_session", session_id, job_id))
def handoff_agent(from_agent_id: str, to_agent_id: str, job_id: str | None = None) -> dict[str, Any]: return _state_result(_call("handoff_agent", from_agent_id, to_agent_id, job_id))
def request_user_takeover(agent_id: str, reason: str) -> dict[str, Any]: return _state_result(_call("request_user_takeover", agent_id, reason))
def request_user_takeover_for_session(session_id: str | None, reason: str) -> dict[str, Any]: return _state_result(_call("request_user_takeover_for_session", session_id, reason))
def acquire_user() -> dict[str, Any]: return _state_result(_call("acquire_user"))
def continue_agent() -> dict[str, Any]: return _state_result(_call("continue_agent"))
def release_control(agent_id: str | None = None) -> dict[str, Any]: return _state_result(_call("release_control", agent_id))
def touch_activity(browser_state: dict[str, Any] | None = None) -> dict[str, Any]: return _state_result(_call("touch_activity", browser_state))
def display_url(*, view_only: bool = False) -> str: return _call("display_url", view_only=view_only)
def guest_exec(command: list[str], timeout: int = 30) -> dict[str, Any]: return _call("guest_exec", command, timeout=timeout)
def _guest_stdout(result: dict[str, Any]) -> bytes:
    raw = str(result.get("out-data") or "")
    return base64.b64decode(raw) if raw else b""
def guest_upload(source: Path, destination: str, *, chunk_bytes: int = 12 * 1024) -> int:
    script = "import base64,sys;open(sys.argv[1],sys.argv[2]).write(base64.b64decode(sys.argv[3]))"
    total, mode = 0, "wb"
    with Path(source).open("rb") as stream:
        while chunk := stream.read(max(1024, int(chunk_bytes))):
            result = guest_exec(["/usr/bin/python3", "-c", script, destination, mode, base64.b64encode(chunk).decode("ascii")], timeout=30)
            if int(result.get("exitcode") or 0) != 0: raise ComputerError("Guest file upload failed.")
            total += len(chunk); mode = "ab"
    if total == 0:
        result = guest_exec(["/usr/bin/python3", "-c", "import sys;open(sys.argv[1],'wb').close()", destination], timeout=15)
        if int(result.get("exitcode") or 0) != 0: raise ComputerError("Guest file upload failed.")
    return total
def guest_download(source: str, destination: Path, *, max_bytes: int, chunk_bytes: int = 12 * 1024) -> int:
    script = "import base64,sys;f=open(sys.argv[1],'rb');f.seek(int(sys.argv[2]));sys.stdout.write(base64.b64encode(f.read(int(sys.argv[3]))).decode())"
    total = 0
    with Path(destination).open("wb") as output:
        while True:
            result = guest_exec(["/usr/bin/python3", "-c", script, source, str(total), str(max(1024, int(chunk_bytes)))], timeout=30)
            if int(result.get("exitcode") or 0) != 0: raise ComputerError("Guest file download failed.")
            encoded = _guest_stdout(result).strip(); data = base64.b64decode(encoded) if encoded else b""
            if not data: break
            total += len(data)
            if total > int(max_bytes): raise ValueError("Company Computer file transfer exceeds the allowed size.")
            output.write(data)
    return total
def _row() -> dict[str, Any]: return _state_result(_call("_row"))
def _session_agent_id(session_id: str | None) -> str: return _call("_session_agent_id", session_id)
