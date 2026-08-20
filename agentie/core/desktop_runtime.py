from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agentie.core.wsl_bridge import list_files as list_linux_files
from agentie.core.wsl_bridge import read_text_file as read_linux_text_file
from agentie.core.wsl_bridge import run_terminal as run_linux_terminal
from agentie.core.wsl_desktop import ensure_started as ensure_wsl_desktop, status as wsl_status, stop as stop_wsl_desktop

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
    if low in {"computer status", "desktop status"}:
        return "status"
    if re.fullmatch(r"(?:open|show|view|look at) (?:the )?(?:workspace )?files", low) or low in {"files", "file manager", "open file manager", "open computer files"}:
        return "files"
    if low in {"linux files", "show linux files", "open linux files", "show computer linux files"}:
        return "linux files"
    if re.fullmatch(r"(?:open|show|view) computer notes", low):
        return "notes"
    if re.fullmatch(r"(?:open|show|view) computer tasks", low):
        return "tasks"
    if re.fullmatch(r"(?:open|show|view) computer plugins", low):
        return "plugins"
    if low in {"open terminal", "show terminal", "terminal", "open the terminal", "open computer terminal"}:
        return "terminal"
    m = re.match(r"^(?:run|execute)\s+(.+?)\s+(?:in|using)\s+(?:the\s+)?(?:linux\s+)?terminal$", text, re.I)
    if m:
        return "terminal " + m.group(1).strip()
    m = re.match(r"^(?:read|open|show)\s+(?:the\s+)?linux file\s+(.+)$", text, re.I)
    if m:
        return "linux file " + m.group(1).strip()
    return None


def _real_desktop_card(info: dict[str, Any], app: str = "desktop") -> dict[str, Any]:
    return desktop_card(
        app,
        mode="wsl",
        running=bool(info.get("running")),
        novnc_url=info.get("novnc_url"),
        kasmvnc_url=info.get("kasmvnc_url") or info.get("novnc_url"),
        chrome_ready=bool(info.get("chrome_ready")),
        setup_required=bool(info.get("setup_required")),
        setup_command=info.get("setup_command"),
        distro=info.get("distro"),
    )


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
    low = command.lower().strip()
    try:
        if low in {"start", "start real desktop", "home", "desktop", "show home"}:
            info = ensure_wsl_desktop()
            message = str(info.get("message") or "Agentie Computer ready.")
            if info.get("setup_required"):
                message += " Run the one-time setup command shown in the Computer card."
            return {"message": message, "card": _real_desktop_card(info)}
        if low in {"status", "real desktop status"}:
            info = wsl_status()
            return {"message": "Agentie Computer is running." if info.get("running") else "Agentie Computer is stopped.", "card": _real_desktop_card(info)}
        if low in {"stop", "shutdown", "power off"}:
            info = stop_wsl_desktop()
            return {"message": str(info.get("message") or "Agentie Computer stopped."), "card": _real_desktop_card(info, "stopped")}
        if low in {"files", "open files", "show files"}:
            return {"message": "Agentie host workspace files.", "card": desktop_card("files", items=_file_items(), workspace="host")}
        if low.startswith("open file "):
            name = command[10:].strip(); item = _read_text(name)
            return {"message": f"Opened {item['name']}.", "card": desktop_card("file", file=item, workspace="host")}
        if low in {"linux files", "open linux files", "show linux files"}:
            result = list_linux_files()
            return {"message": "Linux workspace files.", "card": desktop_card("files", items=result["items"], workspace=result["workspace"], path=result["path"], mode="wsl")}
        if low.startswith("linux files "):
            result = list_linux_files(command[len("linux files "):].strip())
            return {"message": "Linux workspace files.", "card": desktop_card("files", items=result["items"], workspace=result["workspace"], path=result["path"], mode="wsl")}
        if low.startswith("linux file "):
            item = read_linux_text_file(command[len("linux file "):].strip())
            return {"message": f"Opened {item['path']} from Linux.", "card": desktop_card("file", file=item, workspace=item["workspace"], mode="wsl")}
        if low in {"notes", "open notes"}:
            return {"message": "Notes.", "card": desktop_card("notes", items=_read_json("notes.json", []))}
        if low in {"tasks", "open tasks"}:
            return {"message": "Tasks.", "card": desktop_card("tasks", items=_read_json("tasks.json", []))}
        if low in {"plugins", "open plugins"}:
            return {"message": "Plugins.", "card": desktop_card("plugins", items=_read_json("mcp_servers.json", []))}
        if low == "terminal":
            info = ensure_wsl_desktop()
            return {"message": "Agentie Computer terminal is available on the desktop.", "card": _real_desktop_card(info)}
        if low.startswith("terminal "):
            result = run_linux_terminal(command[9:])
            return {"message": f"Linux terminal command exited with code {result['exit_code']}.", "card": desktop_card("terminal", terminal=result, mode="wsl")}
    except FileNotFoundError as exc:
        message = f"Linux file or folder not found: {exc}"
        return {"message": message, "card": desktop_card("error", error=message)}
    except (ValueError, RuntimeError) as exc:
        return {"message": str(exc), "card": desktop_card("error", error=str(exc))}
    return {"message": "Unknown desktop command.", "card": desktop_card("error", error="Unknown desktop command")}
