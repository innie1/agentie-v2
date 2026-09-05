from __future__ import annotations

"""Stable facade for Agentie's single QEMU Company Computer runtime."""

import base64
import os
from pathlib import Path
from types import ModuleType
from typing import Any

from agentie.core.company_computer import ComputerError
from agentie.core.company_computer import IDLE_SECONDS as IDLE_SECONDS


def backend_name(system: str | None = None) -> str:
    override = os.getenv("AGENTIE_COMPUTER_BACKEND", "").strip().lower()
    if override and override not in {"qemu", "qemu_hvf", "qemu_kvm", "qemu_whpx"}:
        raise ComputerError("Agentie Company Computer uses QEMU on Windows, macOS, and Linux.")
    return "qemu"


def _backend() -> ModuleType:
    from agentie.core import company_computer as backend
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
def acquire_user() -> dict[str, Any]:
    _call("acquire_user")
    return status()
def continue_agent() -> dict[str, Any]:
    _call("continue_agent")
    return status()
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
