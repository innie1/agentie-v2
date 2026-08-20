from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

WORKSPACE = Path.cwd() / "workspace"


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
            items.append({"name": path.name, "kind": "folder" if path.is_dir() else "file", "size_bytes": 0 if path.is_dir() else stat.st_size, "modified": stat.st_mtime, "suffix": path.suffix.lower()})
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


def _terminal(command: str) -> dict[str, Any]:
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
        raise ValueError("That command is not enabled in the Agentie desktop terminal yet. Use Files/Browser apps or Agentie's existing Python/code tools for broader execution.")
    try:
        proc = subprocess.run(allowed, cwd=str(Path.cwd()), capture_output=True, text=True, timeout=12, shell=False)
    except FileNotFoundError:
        raise ValueError(f"Command not found: {allowed[0]}")
    except subprocess.TimeoutExpired:
        raise ValueError("Terminal command timed out after 12 seconds.")
    output = ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")).strip()
    return {"command": raw, "output": output[:50000], "exit_code": proc.returncode}


def desktop_card(app: str = "home", **data: Any) -> dict[str, Any]:
    return {"type": "desktop_view", "app": app, **data}


def _natural_command(text: str) -> str | None:
    low = " ".join(text.lower().split()).strip(" .?!")
    if low in {"show desktop", "open desktop", "desktop", "go home", "show home", "computer home", "open home"}:
        return "home"
    if low in {"file manager", "open file manager", "open the file manager", "show computer files", "open computer files"}:
        return "files"
    if low in {"open computer notes", "show computer notes"}:
        return "notes"
    if low in {"open computer tasks", "show computer tasks"}:
        return "tasks"
    if low in {"open computer plugins", "show computer plugins"}:
        return "plugins"
    if low in {"open terminal", "show terminal", "terminal", "open the terminal"}:
        return "terminal"
    m = re.match(r"^(?:run|execute)\s+(.+?)\s+(?:in|using)\s+(?:the\s+)?terminal$", text, re.I)
    if m:
        return "terminal " + m.group(1).strip()
    m = re.match(r"^(?:in\s+(?:the\s+)?terminal\s+)?run\s+(.+)$", text, re.I)
    if m and not re.search(r"\bpython\b", low):
        return "terminal " + m.group(1).strip()
    return None


def route_desktop_request(message: str) -> dict[str, Any] | None:
    text = " ".join(str(message or "").strip().split())
    lower = text.lower()
    prefix = "desktop control:"
    if lower.startswith(prefix):
        command = text[len(prefix):].strip()
    else:
        command = _natural_command(text)
        if command is None:
            return None
    low = command.lower()
    try:
        if low in {"home", "desktop", "show home"}:
            return {"message": "Desktop home.", "card": desktop_card("home")}
        if low in {"files", "open files", "show files"}:
            return {"message": "Workspace files.", "card": desktop_card("files", items=_file_items())}
        if low.startswith("open file "):
            name = command[10:].strip(); item = _read_text(name)
            return {"message": f"Opened {item['name']}.", "card": desktop_card("file", file=item)}
        if low in {"notes", "open notes"}:
            return {"message": "Notes.", "card": desktop_card("notes", items=_read_json("notes.json", []))}
        if low in {"tasks", "open tasks"}:
            return {"message": "Tasks.", "card": desktop_card("tasks", items=_read_json("tasks.json", []))}
        if low in {"plugins", "open plugins"}:
            return {"message": "Plugins.", "card": desktop_card("plugins", items=_read_json("mcp_servers.json", []))}
        if low == "terminal":
            return {"message": "Terminal ready.", "card": desktop_card("terminal", terminal={"command": "", "output": "Agentie Desktop Terminal\nWorkspace: " + str(WORKSPACE.resolve()), "exit_code": 0})}
        if low.startswith("terminal "):
            result = _terminal(command[9:])
            return {"message": "Terminal command completed.", "card": desktop_card("terminal", terminal=result)}
    except ValueError as exc:
        return {"message": str(exc), "card": desktop_card("error", error=str(exc))}
    return {"message": "Unknown desktop command.", "card": desktop_card("error", error="Unknown desktop command")}
