from __future__ import annotations

import base64
import re
import shlex
from typing import Any

from agentie.core import company_computer as computer
from agentie.core.company_computer_files import download_guest_file, upload_workspace_file
from agentie.tools.approval_tools import approval_is_granted, consume_approval, create_approval

_MAX_COMMAND = 4000
_SAFE_PACKAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+_.:-]{0,79}$")
_SYSTEM_CHANGE = re.compile(
    r"(?:^|[;&|]\s*)(?:sudo\s+)?(?:apt|apt-get|aptitude|dpkg|snap|flatpak|systemctl|service|useradd|userdel|usermod|groupadd|groupdel|mount|umount|mkfs(?:\.[a-z0-9]+)?|fdisk|parted)\b"
    r"|\b(?:pip|pip3|python\s+-m\s+pip|npm|pnpm|yarn|cargo|gem|go)\s+(?:install|uninstall|remove|add)\b"
    r"|\b(?:chmod|chown|chgrp|setfacl)\b"
    r"|(?:^|\s)/(?:etc|usr|opt|boot|var/lib|var/spool)(?:/|\s|$)",
    re.I,
)
_DESTRUCTIVE = re.compile(r"(?:^|[;&|]\s*)(?:sudo\s+)?(?:rm|shred|truncate|wipefs|dd)\b|\b(?:reboot|shutdown|poweroff|halt)\b", re.I)
_EXTERNAL_WRITE = re.compile(
    r"\bgit\s+push\b|\b(?:scp|sftp|rsync)\b|\bcurl\b[^\n]*(?:-X|--request)\s*(?:POST|PUT|PATCH|DELETE)\b|\bgh\s+(?:pr\s+merge|release\s+create|api\s+--method\s+(?:POST|PUT|PATCH|DELETE))\b",
    re.I,
)

_APP_ALIASES = {
    "browser": ["/usr/bin/chromium"],
    "chromium": ["/usr/bin/chromium"],
    "chrome": ["/usr/bin/chromium"],
    "terminal": ["/usr/bin/xterm"],
    "xterm": ["/usr/bin/xterm"],
    "files": ["/usr/bin/pcmanfm", "/home/agentie"],
    "file manager": ["/usr/bin/pcmanfm", "/home/agentie"],
}


def _agent_id(session_id: str | None) -> str:
    return computer._session_agent_id(session_id)


def _decode(value: Any) -> str:
    encoded = str(value or "")
    if not encoded:
        return ""
    try:
        return base64.b64decode(encoded).decode("utf-8", "replace")
    except Exception:
        return ""


def _approval_reason(command: str) -> str | None:
    if _DESTRUCTIVE.search(command):
        return "This Company Computer command can permanently delete data or stop the guest system."
    if _SYSTEM_CHANGE.search(command):
        return "This Company Computer command installs software or makes a persistent system-level change."
    if _EXTERNAL_WRITE.search(command):
        return "This Company Computer command can change data on an external service."
    return None


def _approval_action(command: str) -> str:
    compact = " ".join(command.split())
    return f"computer:guest:{compact}"[:500]


def _run_as_agentie(command: str, timeout: int) -> dict[str, Any]:
    return computer.guest_exec(
        [
            "/usr/sbin/runuser",
            "-u",
            "agentie",
            "--",
            "/usr/bin/env",
            "HOME=/home/agentie",
            "USER=agentie",
            "LOGNAME=agentie",
            "DISPLAY=:0",
            "XDG_RUNTIME_DIR=/tmp/runtime-agentie",
            "/bin/bash",
            "-lc",
            command,
        ],
        timeout=timeout,
    )


def _run_as_root(command: str, timeout: int) -> dict[str, Any]:
    return computer.guest_exec(["/bin/bash", "-lc", command], timeout=timeout)


def _execute_command(raw: str, agent_id: str, reason: str | None, timeout: int) -> dict[str, Any]:
    computer.acquire_agent(agent_id)
    try:
        root_required = bool(reason and _SYSTEM_CHANGE.search(raw))
        result = _run_as_root(raw, timeout) if root_required else _run_as_agentie(raw, timeout)
        stdout = _decode(result.get("out-data"))
        stderr = _decode(result.get("err-data"))
        exit_code = int(result.get("exitcode") or 0)
        terminal = {
            "command": raw,
            "output": stdout[:50000],
            "error": stderr[:20000],
            "exit_code": exit_code,
            "guest": "company-default",
            "user": "root" if root_required else "agentie",
            "persistent": True,
            "truncated": bool(result.get("out-truncated") or result.get("err-truncated")),
        }
        return {
            "message": "Company Computer terminal command completed." if exit_code == 0 else f"Company Computer terminal command exited with code {exit_code}.",
            "card": {"type": "desktop_view", "app": "terminal", "mode": "qemu", "terminal": terminal},
            "terminal": terminal,
        }
    finally:
        try:
            computer.release_control(agent_id)
        except Exception:
            pass


def execute_approved_guest_command(command: str, agent_id: str, *, timeout: int = 300) -> dict[str, Any]:
    """Execute a command whose specific approval has just been resolved.

    This is intentionally separate from `run_guest_command` so approval
    resolution can execute the approved action exactly once without creating a
    second approval or relying on a retry from the UI.
    """
    raw = str(command or "").strip()
    owner = str(agent_id or "").strip()
    if not raw or not owner:
        raise ValueError("Approved Company Computer command is missing command or agent ownership metadata.")
    if len(raw) > _MAX_COMMAND:
        raise ValueError("Company Computer terminal commands are limited to 4000 characters.")
    reason = _approval_reason(raw)
    if reason is None:
        raise ValueError("Approved Company Computer command is no longer classified as consequential.")
    return _execute_command(raw, owner, reason, timeout)


def run_guest_command(command: str, session_id: str | None = None, *, timeout: int = 120) -> dict[str, Any]:
    """Execute a real command inside the persistent Company Computer.

    Normal commands run as the unprivileged `agentie` guest user. Destructive,
    external-write, package-install, and system-changing commands use the
    existing Agentie approval system before they can execute.
    """
    raw = str(command or "").strip()
    if not raw:
        raise ValueError("A Company Computer terminal command is required.")
    if len(raw) > _MAX_COMMAND:
        raise ValueError("Company Computer terminal commands are limited to 4000 characters.")

    reason = _approval_reason(raw)
    action = _approval_action(raw)
    if reason and not approval_is_granted(action):
        item = create_approval(
            action,
            reason + f" Command: {raw}",
            {
                "kind": "computer_guest_command",
                "command": raw,
                "agent_id": _agent_id(session_id),
                "persistent_change": bool(_SYSTEM_CHANGE.search(raw)),
                "destructive": bool(_DESTRUCTIVE.search(raw)),
                "external_write": bool(_EXTERNAL_WRITE.search(raw)),
            },
        )
        return {
            "message": "This Company Computer command needs approval before it can run.",
            "card": {"type": "approvals", "items": [item]},
            "approval_required": True,
        }
    if reason:
        consume_approval(action)
    return _execute_command(raw, _agent_id(session_id), reason, timeout)


def install_guest_package(package: str, session_id: str | None = None) -> dict[str, Any]:
    name = str(package or "").strip()
    if not _SAFE_PACKAGE.fullmatch(name):
        raise ValueError("Package names may contain only letters, numbers, +, _, ., :, and -.")
    quoted = shlex.quote(name)
    command = (
        "DEBIAN_FRONTEND=noninteractive apt-get update && "
        f"DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends {quoted}"
    )
    return run_guest_command(command, session_id, timeout=300)


def launch_guest_app(app: str, session_id: str | None = None) -> dict[str, Any]:
    key = " ".join(str(app or "").lower().split())
    argv = _APP_ALIASES.get(key)
    if not argv:
        raise ValueError("Supported Company Computer apps are Chromium, Terminal, and File Manager.")
    agent_id = _agent_id(session_id)
    computer.acquire_agent(agent_id)
    try:
        command = [
            "/usr/sbin/runuser",
            "-u",
            "agentie",
            "--",
            "/usr/bin/env",
            "HOME=/home/agentie",
            "USER=agentie",
            "LOGNAME=agentie",
            "DISPLAY=:0",
            "XDG_RUNTIME_DIR=/tmp/runtime-agentie",
            "/usr/bin/setsid",
            "-f",
            *argv,
        ]
        result = computer.guest_exec(command, timeout=30)
        exit_code = int(result.get("exitcode") or 0)
        if exit_code != 0:
            raise computer.ComputerError(_decode(result.get("err-data")) or f"Could not open {app} inside Agentie Computer.")
        return {
            "message": f"Opened {key} inside Agentie Computer.",
            "card": {"type": "desktop_view", "app": "desktop", "mode": "qemu", **computer.status(), "last_action": f"Opened {key}"},
        }
    finally:
        try:
            computer.release_control(agent_id)
        except Exception:
            pass


def route_company_computer_command(message: str, session_id: str | None = None) -> dict[str, Any] | None:
    text = " ".join(str(message or "").strip().split())
    if not text:
        return None

    match = re.match(r"^(?:computer|company computer)\s+terminal\s*:\s*(.+)$", text, re.I)
    if not match:
        match = re.match(r"^(?:run|execute)\s+(.+?)\s+(?:in|using)\s+(?:the\s+)?(?:company\s+computer\s+)?terminal$", text, re.I)
    if match:
        return run_guest_command(match.group(1).strip(), session_id)

    match = re.match(r"^install\s+([A-Za-z0-9][A-Za-z0-9+_.:-]{0,79})\s+(?:on|in)\s+(?:the\s+)?(?:company\s+)?computer$", text, re.I)
    if match:
        return install_guest_package(match.group(1), session_id)

    match = re.match(r"^open\s+(browser|chromium|chrome|terminal|xterm|files|file manager)\s+(?:on|in)\s+(?:the\s+)?(?:company\s+)?computer$", text, re.I)
    if match:
        return launch_guest_app(match.group(1), session_id)

    match = re.match(r"^(?:copy|upload|send)\s+(.+?)\s+to\s+(?:the\s+)?(?:company\s+)?computer$", text, re.I)
    if match:
        item = upload_workspace_file(match.group(1).strip())
        return {
            "message": f"Copied {item['name']} into Agentie Computer.",
            "card": {"type": "desktop_view", "app": "files", "mode": "qemu", "transfer": item},
        }

    match = re.match(r"^(?:copy|download|export)\s+(.+?)\s+from\s+(?:the\s+)?(?:company\s+)?computer(?:\s+as\s+([^\\/]+))?$", text, re.I)
    if match:
        item = download_guest_file(match.group(1).strip(), (match.group(2) or "").strip() or None)
        return {
            "message": f"Copied {item['name']} from Agentie Computer into the Agentie workspace.",
            "card": {"type": "desktop_view", "app": "files", "mode": "qemu", "transfer": item},
        }
    return None
