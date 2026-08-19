from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agentie.core.mcp_client import (
    _approval_response,
    _error_text,
    _filesystem_root,
    execute_tool,
    inspect_server,
    list_servers,
)

_FILE_EXTENSIONS = (
    "pdf", "json", "txt", "md", "csv", "tsv", "xlsx", "xls", "docx", "doc", "pptx", "ppt",
    "py", "js", "ts", "yaml", "yml", "toml", "ini", "log", "zip", "sqlite", "sqlite3",
)
_EXT_PATTERN = "|".join(_FILE_EXTENSIONS)


def _filesystem_server() -> dict[str, Any] | None:
    for server in list_servers():
        if str(server.get("name") or "").lower() == "filesystem":
            return server
    return None


def _filename(text: str) -> str | None:
    match = re.search(rf"(?<![\w.-])([\w][\w .()\-]*\.(?:{_EXT_PATTERN}))(?![\w.-])", text, re.I)
    return match.group(1).strip(" .?!\"'`") if match else None


def _extension_search(text: str) -> str | None:
    low = text.lower()
    if not re.search(r"\b(?:find|search|locate)\b", low):
        return None
    wildcard = re.search(rf"\*\.({_EXT_PATTERN})\b", low)
    if wildcard:
        return f"*.{wildcard.group(1).lower()}"
    named = re.search(rf"\b({_EXT_PATTERN})\s+files?\b", low)
    if named:
        return f"*.{named.group(1).lower()}"
    return None


def _allowed_directories_request(text: str) -> bool:
    low = " ".join(text.lower().split()).strip(" .?!")
    return bool(
        re.search(r"\b(?:what|which|show|list|tell me)\b.*\b(?:directories|folders)\b.*\b(?:can|allowed|access|accessible)\b", low)
        or re.search(r"\b(?:directories|folders)\b.*\b(?:can i|am i allowed to)\b.*\baccess\b", low)
    )


def _tool_name(info: dict[str, Any], *names: str) -> str | None:
    available = {str(item.get("name") or "").lower(): str(item.get("name") or "") for item in info.get("tools") or []}
    for name in names:
        if name.lower() in available:
            return available[name.lower()]
    return None


def _join_root(root: str | None, filename: str) -> str | None:
    if re.match(r"^[A-Za-z]:\\", filename) or filename.startswith("/"):
        return filename
    if not root:
        return None
    return str(Path(root) / filename)


def _choice(text: str, server: dict[str, Any], info: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    low = text.lower()
    root = _filesystem_root(server)

    if _allowed_directories_request(text):
        tool = _tool_name(info, "list_allowed_directories")
        if tool:
            return tool, {}

    pattern = _extension_search(text)
    if pattern and root:
        tool = _tool_name(info, "search_files")
        if tool:
            return tool, {"path": root, "pattern": pattern}

    filename = _filename(text)
    if not filename:
        return None
    path = _join_root(root, filename)
    if not path:
        return None

    if re.search(r"\b(?:information|info|details|metadata|size|modified|created)\b", low):
        tool = _tool_name(info, "get_file_info")
        if tool:
            return tool, {"path": path}

    if re.search(r"\b(?:read|open|show|display|inspect|view)\b", low):
        tool = _tool_name(info, "read_text_file", "read_file")
        if tool:
            return tool, {"path": path}

    return None


async def route_capability_preflight(message: str) -> dict[str, Any] | None:
    """Intercept only high-confidence filesystem requests before generic local parsing.

    This intentionally does not handle generic "list files" requests, timers, tasks,
    reminders, calculations, memory, Python, or other native Agentie behavior.
    """
    text = " ".join(str(message or "").strip().split())
    if not text:
        return None
    if not (_filename(text) or _extension_search(text) or _allowed_directories_request(text)):
        return None

    server = _filesystem_server()
    if not server:
        return None
    try:
        info = await inspect_server("filesystem")
    except Exception:
        return None

    choice = _choice(text, server, info)
    if not choice:
        return None
    tool_name, arguments = choice
    canonical = f"Call MCP filesystem tool {tool_name} with {json.dumps(arguments, ensure_ascii=False)}"
    approval = _approval_response("filesystem", tool_name, arguments, canonical, natural=True)
    if approval.get("approved"):
        try:
            return await execute_tool("filesystem", tool_name, arguments)
        except Exception as exc:
            return {"message": f"The approved MCP tool call could not complete: {_error_text(exc)}", "card": None}
    return approval
