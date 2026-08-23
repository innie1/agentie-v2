from __future__ import annotations

import re
from typing import Any

from agentie.core import company_computer as computer
from agentie.core.company_computer_guest_setup import ensure_guest_runtime

_KEY_MAP = {
    "enter": "Return",
    "return": "Return",
    "tab": "Tab",
    "escape": "Escape",
    "esc": "Escape",
    "backspace": "BackSpace",
    "delete": "Delete",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "pageup": "Page_Up",
    "pagedown": "Page_Down",
    "home": "Home",
    "end": "End",
    "ctrl+l": "ctrl+l",
    "ctrl+a": "ctrl+a",
    "ctrl+c": "ctrl+c",
    "ctrl+v": "ctrl+v",
}


def _agent_id(session_id: str | None) -> str:
    return computer._session_agent_id(session_id)


def _ensure_xdotool() -> None:
    """Prepare Agentie's internal desktop automation component in old guests too."""
    check = computer.guest_exec(["/usr/bin/test", "-x", "/usr/bin/xdotool"], timeout=15)
    if int(check.get("exitcode") or 0) == 0:
        return
    install = computer.guest_exec(
        [
            "/bin/bash",
            "-lc",
            "DEBIAN_FRONTEND=noninteractive apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends xdotool",
        ],
        timeout=300,
    )
    if int(install.get("exitcode") or 0) != 0:
        raise computer.ComputerError("Could not prepare the Company Computer desktop automation component.")


def _xdotool(args: list[str], session_id: str | None = None, *, timeout: int = 30) -> dict[str, Any]:
    ensure_guest_runtime()
    agent_id = _agent_id(session_id)
    computer.acquire_agent(agent_id)
    try:
        _ensure_xdotool()
        result = computer.guest_exec(
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
                "/usr/bin/xdotool",
                *args,
            ],
            timeout=timeout,
        )
        exit_code = int(result.get("exitcode") or 0)
        if exit_code != 0:
            raise computer.ComputerError(f"Desktop input command exited with code {exit_code}.")
        computer.touch_activity()
        return computer.status()
    finally:
        try:
            computer.release_control(agent_id)
        except Exception:
            pass


def desktop_click(x: int, y: int, session_id: str | None = None, *, button: int = 1) -> dict[str, Any]:
    if not 0 <= int(x) <= 10000 or not 0 <= int(y) <= 10000:
        raise ValueError("Desktop coordinates must be between 0 and 10000.")
    if button not in {1, 2, 3}:
        raise ValueError("Desktop mouse button must be 1, 2, or 3.")
    return _xdotool(["mousemove", "--sync", str(int(x)), str(int(y)), "click", str(button)], session_id)


def desktop_type(text: str, session_id: str | None = None) -> dict[str, Any]:
    value = str(text or "")
    if not value:
        raise ValueError("Text is required for desktop typing.")
    if len(value) > 5000:
        raise ValueError("Desktop typing is limited to 5000 characters at a time.")
    return _xdotool(["type", "--clearmodifiers", "--delay", "12", "--", value], session_id)


def desktop_key(key: str, session_id: str | None = None) -> dict[str, Any]:
    clean = "".join(str(key or "").lower().split())
    mapped = _KEY_MAP.get(clean)
    if not mapped:
        raise ValueError("Unsupported desktop key. Use Enter, Tab, Escape, arrows, PageUp/PageDown, Home/End, or Ctrl+A/C/V/L.")
    return _xdotool(["key", "--clearmodifiers", mapped], session_id)


def desktop_scroll(direction: str, session_id: str | None = None, *, steps: int = 4) -> dict[str, Any]:
    clean = str(direction or "").lower().strip()
    if clean not in {"up", "down"}:
        raise ValueError("Desktop scroll direction must be up or down.")
    count = max(1, min(int(steps), 20))
    button = "4" if clean == "up" else "5"
    return _xdotool(["click", "--repeat", str(count), "--delay", "35", button], session_id)


def route_desktop_control(message: str, session_id: str | None = None) -> dict[str, Any] | None:
    text = " ".join(str(message or "").strip().split())
    prefix = re.match(r"^(?:computer|company computer)\s+control\s*:\s*(.+)$", text, re.I)
    if not prefix:
        return None
    command = prefix.group(1).strip()

    match = re.match(r"^click\s+at\s+(\d+)\s*[, ]\s*(\d+)$", command, re.I)
    if match:
        info = desktop_click(int(match.group(1)), int(match.group(2)), session_id)
        return {"message": f"Clicked the Company Computer at {match.group(1)}, {match.group(2)}.", "card": {"type": "desktop_view", "app": "desktop", "mode": "qemu", **info, "last_action": command}}

    match = re.match(r"^type\s+(?:focused\s*:\s*)?(.+)$", command, re.I)
    if match:
        info = desktop_type(match.group(1), session_id)
        return {"message": "Typed into the focused Company Computer control.", "card": {"type": "desktop_view", "app": "desktop", "mode": "qemu", **info, "last_action": "typed text"}}

    match = re.match(r"^(?:press|key)\s+(.+)$", command, re.I)
    if match:
        info = desktop_key(match.group(1), session_id)
        return {"message": f"Pressed {match.group(1)} on the Company Computer.", "card": {"type": "desktop_view", "app": "desktop", "mode": "qemu", **info, "last_action": command}}

    match = re.match(r"^scroll\s+(up|down)(?:\s+(\d+))?$", command, re.I)
    if match:
        info = desktop_scroll(match.group(1), session_id, steps=int(match.group(2) or 4))
        return {"message": f"Scrolled {match.group(1).lower()} on the Company Computer.", "card": {"type": "desktop_view", "app": "desktop", "mode": "qemu", **info, "last_action": command}}

    raise ValueError("Unknown Company Computer control command.")
