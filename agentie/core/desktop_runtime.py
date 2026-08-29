from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from agentie.core.company_computer_backend import (
    ComputerError,
    acquire_user,
    continue_agent,
    resume as resume_computer,
    start as start_computer,
    status as computer_status,
    stop as stop_computer,
    suspend as suspend_computer,
)
from agentie.core.company_computer_commands import route_company_computer_command
from agentie.core.company_computer_desktop import route_desktop_control
from agentie.core.company_computer_guest_setup import ensure_guest_runtime
from agentie.core.company_computer_idle import start_idle_coordinator

WORKSPACE = Path.cwd() / "workspace"
start_idle_coordinator()


def _safe_path(name: str) -> Path:
    value = str(name or "").strip().strip('"\'')
    target = (WORKSPACE / value).resolve()
    root = WORKSPACE.resolve()
    if target != root and root not in target.parents:
        raise ValueError("That path is outside the Agentie desktop workspace.")
    return target


def _file_items() -> list[dict[str, Any]]:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    items = []
    for path in sorted(WORKSPACE.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        try:
            stat = path.stat()
            items.append(
                {
                    "name": path.name,
                    "kind": "folder" if path.is_dir() else "file",
                    "size_bytes": 0 if path.is_dir() else stat.st_size,
                    "modified": stat.st_mtime,
                    "suffix": path.suffix.lower(),
                }
            )
        except OSError:
            continue
    return items


def _read_json(name: str, default: Any) -> Any:
    path = _safe_path(name)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_text(name: str) -> dict[str, Any]:
    path = _safe_path(name)
    if not path.exists() or not path.is_file():
        raise ValueError("File not found in the Agentie workspace.")
    if path.stat().st_size > 1_000_000:
        raise ValueError("That file is too large for the desktop text viewer.")
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".sqlite3", ".db"}:
        return {"name": path.name, "binary": True, "size_bytes": path.stat().st_size}
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"name": path.name, "binary": True, "size_bytes": path.stat().st_size}
    return {"name": path.name, "binary": False, "size_bytes": path.stat().st_size, "content": text[:200000]}


def _host_terminal(command: str) -> dict[str, Any]:
    """Compatibility-only safe host workspace terminal.

    Real agent shell work belongs in the persistent Linux guest. This helper
    remains only for explicit legacy `Desktop control: terminal ...` workspace
    inspection. It never exposes arbitrary host shell access.
    """
    raw = str(command or "").strip()
    if not raw:
        return {"command": "", "output": "", "exit_code": 0}
    if len(raw) > 1000:
        raise ValueError("Terminal command is too long.")
    try:
        parts = shlex.split(raw, posix=os.name != "nt")
    except ValueError as exc:
        raise ValueError(f"Could not parse terminal command: {exc}") from exc
    if not parts:
        return {"command": raw, "output": "", "exit_code": 0}
    cmd = parts[0].lower()
    if cmd in {"pwd", "cd"}:
        return {"command": raw, "output": str(WORKSPACE.resolve()), "exit_code": 0}
    if cmd in {"ls", "dir"}:
        output = "\n".join(("[DIR] " if item["kind"] == "folder" else "      ") + item["name"] for item in _file_items())
        return {"command": raw, "output": output, "exit_code": 0}
    if cmd in {"cat", "type"}:
        if len(parts) < 2:
            raise ValueError("Provide a workspace filename to read.")
        item = _read_text(parts[1])
        return {"command": raw, "output": "Binary file" if item.get("binary") else item.get("content", ""), "exit_code": 0}
    allowed: list[str] | None = None
    if cmd == "git" and len(parts) >= 2 and parts[1].lower() in {"status", "log", "diff", "branch", "show", "rev-parse"}:
        allowed = ["git", *parts[1:]]
    elif cmd in {"python", "python3", "py"} and parts[1:] in (["--version"], ["-V"]):
        allowed = [parts[0], *parts[1:]]
    elif cmd in {"pip", "pip3"} and len(parts) >= 2 and parts[1].lower() in {"list", "show", "freeze"}:
        allowed = [parts[0], *parts[1:]]
    if allowed is None:
        raise ValueError("That host command is not enabled. Use the real Agentie Computer Terminal for full Linux commands.")
    try:
        proc = subprocess.run(allowed, cwd=str(Path.cwd()), capture_output=True, text=True, timeout=12, shell=False)
    except FileNotFoundError:
        raise ValueError(f"Command not found: {allowed[0]}")
    except subprocess.TimeoutExpired:
        raise ValueError("Terminal command timed out after 12 seconds.")
    output = ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")).strip()
    return {"command": raw, "output": output[:50000], "exit_code": proc.returncode}


_terminal = _host_terminal


def desktop_card(app: str = "home", **data: Any) -> dict[str, Any]:
    return {"type": "desktop_view", "app": app, **data}


def _natural_command(text: str) -> str | None:
    low = " ".join(text.lower().split()).strip(" .?!")
    if low in {"show desktop", "open desktop", "desktop", "go home", "show home", "computer home", "open home", "show computer", "open computer"}:
        return "start"
    if low in {"start computer", "start the computer", "turn on computer", "turn on the computer"}:
        return "start"
    if low in {"stop computer", "stop the computer", "shutdown computer", "shut down computer", "shut down the computer"}:
        return "stop"
    if low in {"suspend computer", "suspend the computer", "sleep computer", "sleep the computer"}:
        return "suspend"
    if low in {"resume computer", "resume the computer", "wake computer", "wake the computer"}:
        return "resume"
    if low in {"computer status", "desktop status"}:
        return "status"
    if low in {"take computer control", "take control", "user control", "take user control"}:
        return "take user control"
    if low in {"continue agent", "return control to agent", "give control back to agent"}:
        return "continue agent"
    if re.fullmatch(r"(?:open|show|view|look at) (?:the )?(?:workspace )?files", low) or low in {"files", "file manager", "open file manager", "open computer files"}:
        return "files"
    if re.fullmatch(r"(?:open|show|view) computer notes", low):
        return "notes"
    if re.fullmatch(r"(?:open|show|view) computer tasks", low):
        return "tasks"
    if re.fullmatch(r"(?:open|show|view) computer plugins", low):
        return "plugins"
    if low in {"open terminal", "show terminal", "terminal", "open the terminal", "open computer terminal"}:
        return "terminal"
    return None


def _real_desktop_card(info: dict[str, Any], app: str = "desktop") -> dict[str, Any]:
    accel = info.get("acceleration") or {}
    profile = info.get("profile") or {}
    return desktop_card(
        app,
        mode=info.get("backend", "qemu"),
        backend=info.get("backend", "qemu"),
        computer_id=info.get("computer_id", "company-default"),
        state=info.get("state", "STOPPED"),
        readiness_stage=info.get("readiness_stage"),
        needs_restart=bool(info.get("needs_restart")),
        running=bool(info.get("running")),
        display_ready=bool(info.get("display_ready")),
        browser_ready=bool(info.get("browser_ready")),
        display_url=info.get("display_url"),
        controller_type=info.get("controller_type"),
        controller_agent_id=info.get("controller_agent_id"),
        job_id=info.get("job_id"),
        takeover_reason=info.get("takeover_reason"),
        persistent=True,
        disk_exists=bool(info.get("disk_exists")),
        accelerator=accel.get("accelerator"),
        acceleration_available=bool(accel.get("available")),
        action=accel.get("action"),
        vm_ram_mb=profile.get("vm_ram_mb"),
        vm_vcpus=profile.get("vm_vcpus"),
        error=info.get("last_error"),
    )


def _error_card(exc: Exception) -> dict[str, Any]:
    info = computer_status()
    return desktop_card(
        "error",
        mode=info.get("backend", "qemu"),
        backend=info.get("backend", "qemu"),
        state=info.get("state"),
        readiness_stage=info.get("readiness_stage"),
        needs_restart=bool(info.get("needs_restart")),
        error=str(exc),
        action=(info.get("acceleration") or {}).get("action"),
    )


def _ensure_visible_computer() -> dict[str, Any]:
    """Start the computer without hiding a healthy display behind guest-control repair."""
    info = start_computer()
    if info.get("display_ready"):
        return info
    ensure_guest_runtime()
    return computer_status()


def route_desktop_request(message: str, session_id: str | None = None) -> dict[str, Any] | None:
    text = " ".join(str(message or "").strip().split())
    if not text:
        return None

    try:
        guest = route_company_computer_command(text, session_id)
        if guest is not None:
            return guest
        desktop_action = route_desktop_control(text, session_id)
        if desktop_action is not None:
            return desktop_action
    except (ValueError, RuntimeError, ComputerError) as exc:
        return {"message": str(exc), "card": _error_card(exc)}

    lower = text.lower()
    prefix = "desktop control:"
    if lower.startswith(prefix):
        command = text[len(prefix):].strip()
    else:
        command = _natural_command(text)
        if command is None:
            return None
    low = command.lower().strip()

    try:
        if low in {"start", "start real desktop", "home", "desktop", "show home"}:
            _ensure_visible_computer()
            info = acquire_user()
            return {"message": "Agentie Computer ready for you.", "card": _real_desktop_card(info)}
        if low in {"take user control", "user control", "take control"}:
            info = computer_status()
            if not info.get("display_ready"):ensure_guest_runtime()
            info = acquire_user()
            return {"message": "User Control enabled on the same Agentie Computer.", "card": _real_desktop_card(info)}
        if low in {"continue agent", "return to agent"}:
            info = continue_agent()
            return {"message": "Control returned to the agent.", "card": _real_desktop_card(info)}
        if low in {"status", "real desktop status"}:
            info = computer_status()
            state = str(info.get("state") or "STOPPED").replace("_", " ").title()
            return {"message": f"Agentie Computer: {state}.", "card": _real_desktop_card(info)}
        if low in {"stop", "shutdown", "power off"}:
            info = stop_computer()
            return {"message": "Agentie Computer stopped.", "card": _real_desktop_card(info, "stopped")}
        if low in {"suspend", "sleep"}:
            info = suspend_computer()
            return {"message": "Agentie Computer suspended.", "card": _real_desktop_card(info, "suspended")}
        if low in {"resume", "wake"}:
            resume_computer()
            info = computer_status()
            if not info.get("display_ready"):ensure_guest_runtime()
            info = acquire_user()
            return {"message": "Agentie Computer resumed for you.", "card": _real_desktop_card(info)}
        if low in {"files", "open files", "show files"}:
            return {"message": "Workspace files.", "card": desktop_card("files", items=_file_items())}
        if low.startswith("open file "):
            name = command[10:].strip()
            item = _read_text(name)
            return {"message": f"Opened {item['name']}.", "card": desktop_card("file", file=item)}
        if low in {"notes", "open notes"}:
            return {"message": "Notes.", "card": desktop_card("notes", items=_read_json("notes.json", []))}
        if low in {"tasks", "open tasks"}:
            return {"message": "Tasks.", "card": desktop_card("tasks", items=_read_json("tasks.json", []))}
        if low in {"plugins", "open plugins"}:
            return {"message": "Plugins.", "card": desktop_card("plugins", items=_read_json("mcp_servers.json", []))}
        if low == "terminal":
            start_computer()
            ensure_guest_runtime()
            info = acquire_user()
            return {"message": "The real Linux Terminal is available inside Agentie Computer.", "card": _real_desktop_card(info)}
        if low.startswith("terminal "):
            result = _host_terminal(command[9:])
            return {"message": "Host workspace command completed.", "card": desktop_card("terminal", terminal=result)}
    except (ValueError, RuntimeError, ComputerError) as exc:
        return {"message": str(exc), "card": _error_card(exc)}
    return {"message": "Unknown desktop command.", "card": desktop_card("error", error="Unknown desktop command")}
