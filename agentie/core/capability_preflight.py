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
WORKSPACE = Path.cwd() / "workspace"


def _filesystem_server() -> dict[str, Any] | None:
    for server in list_servers():
        if str(server.get("name") or "").lower() == "filesystem":
            return server
    return None


def _agentmail_server() -> dict[str, Any] | None:
    for server in list_servers():
        if str(server.get("name") or "").lower() == "agentmail":
            return server
    return None


def _agentmail_settings_path() -> Path:
    return WORKSPACE / "agentmail_settings.json"


def _load_agentmail_settings() -> dict[str, str]:
    path = _agentmail_settings_path()
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _save_agentmail_settings(settings: dict[str, str]) -> None:
    path = _agentmail_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")


def _email_address(text: str) -> str | None:
    match = re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", text, re.I)
    return match.group(0) if match else None


def _agentmail_config(text: str) -> dict[str, Any] | None:
    compact = " ".join(str(text or "").strip().split())
    low = compact.lower().strip(" .?!")
    email_match = re.match(r"^(?:set|save|remember)\s+(?:my\s+)?(?:notification|personal|destination)\s+email\s+(?:to|as)\s+(.+)$", compact, re.I)
    if email_match:
        address = _email_address(email_match.group(1))
        if not address:
            return {"message": "Please provide a valid email address.", "card": None}
        settings = _load_agentmail_settings()
        settings["notification_email"] = address
        _save_agentmail_settings(settings)
        return {"message": f"Saved {address} as your AgentMail notification email.", "card": {"type": "note", "title": "AgentMail settings", "content": f"Notification email: {address}"}}

    inbox_match = re.match(r"^(?:set|save|remember)\s+(?:my\s+)?(?:agentmail\s+)?(?:sender\s+)?inbox(?:\s+id)?\s+(?:to|as)\s+([^\s]+)$", compact, re.I)
    if inbox_match:
        inbox_id = inbox_match.group(1).strip(" .?!\"'`")
        if not inbox_id:
            return {"message": "Please provide an AgentMail inbox ID.", "card": None}
        settings = _load_agentmail_settings()
        settings["inbox_id"] = inbox_id
        _save_agentmail_settings(settings)
        return {"message": "Saved the default AgentMail sender inbox.", "card": {"type": "note", "title": "AgentMail settings", "content": f"Sender inbox: {inbox_id}"}}

    if low in {"show agentmail settings", "agentmail settings", "show my agentmail settings"}:
        settings = _load_agentmail_settings()
        lines = [f"Notification email: {settings.get('notification_email') or 'not set'}", f"Sender inbox: {settings.get('inbox_id') or 'not set'}"]
        return {"message": "Here are the local AgentMail settings.", "card": {"type": "note", "title": "AgentMail settings", "content": "\n".join(lines)}}
    return None


def _agentmail_intent(text: str) -> bool:
    low = " ".join(str(text or "").lower().split())
    return bool(
        re.search(r"\b(?:email|e-mail|mail)\b", low)
        or re.search(r"\b(?:inbox|inboxes)\b", low) and ("agentmail" in low or re.search(r"\b(?:check|list|show|read|search)\b", low))
    )


def _agentmail_body(text: str) -> str | None:
    patterns = (
        r"\b(?:saying|that says|with (?:the )?(?:message|body|text)|message|body)\s*[:=-]?\s*(.+)$",
        r"\bemail\s+me\s+(.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            value = match.group(1).strip().strip("\"'`")
            if value:
                return value
    return None


def _agentmail_subject(text: str) -> str | None:
    match = re.search(r"\bsubject\s*[:=-]?\s*[\"']?(.+?)[\"']?(?=\s+(?:saying|that says|with (?:the )?(?:message|body|text)|message|body)\b|$)", text, re.I)
    return match.group(1).strip(" .\"'`") if match else None


def _agentmail_recipient(text: str, settings: dict[str, str]) -> str | None:
    low = text.lower()
    if re.search(r"\b(?:email|mail|send(?: an?)? email)\s+me\b", low):
        return settings.get("notification_email")
    explicit = _email_address(text)
    return explicit


def _tool_name(info: dict[str, Any], *names: str) -> str | None:
    available = {str(item.get("name") or "").lower(): str(item.get("name") or "") for item in info.get("tools") or []}
    for name in names:
        if name.lower() in available:
            return available[name.lower()]
    return None


def _agentmail_choice(text: str, info: dict[str, Any]) -> tuple[str, dict[str, Any]] | dict[str, Any] | None:
    low = " ".join(text.lower().split())
    settings = _load_agentmail_settings()

    if re.search(r"\b(?:list|show|what are|check)\b.*\b(?:agentmail\s+)?inboxes\b", low) or low in {"agentmail inboxes", "list agentmail inboxes"}:
        tool = _tool_name(info, "list_inboxes")
        return (tool, {"limit": 10}) if tool else None

    if re.search(r"\b(?:check|list|show|read)\b.*\b(?:email|emails|messages|inbox)\b", low) and not re.search(r"\b(?:send|email|mail)\s+(?:me|to|[\w.+-]+@)", low):
        inbox_id = settings.get("inbox_id")
        if not inbox_id:
            return {"message": "I need your default AgentMail inbox ID first. Say “List my AgentMail inboxes”, then “Set my AgentMail inbox to <inboxId>”.", "card": None}
        tool = _tool_name(info, "list_messages")
        return (tool, {"inboxId": inbox_id, "limit": 10}) if tool else None

    if re.search(r"\b(?:send|email|mail)\b", low):
        inbox_id = settings.get("inbox_id")
        if not inbox_id:
            return {"message": "I need the AgentMail inbox to send from. Say “List my AgentMail inboxes”, then “Set my AgentMail inbox to <inboxId>”.", "card": None}
        recipient = _agentmail_recipient(text, settings)
        if not recipient:
            if re.search(r"\b(?:email|mail)\s+me\b", low):
                return {"message": "I need your destination email first. Say “Set my notification email to you@example.com”.", "card": None}
            return {"message": "Tell me who to email, for example “Email person@example.com saying hello”.", "card": None}
        tool = _tool_name(info, "send_message")
        if not tool:
            return None
        body = _agentmail_body(text) or "Message from Agentie."
        subject = _agentmail_subject(text) or "Agentie update"
        return tool, {"inboxId": inbox_id, "to": [recipient], "subject": subject, "text": body}

    if re.search(r"\bsearch\b.*\b(?:email|emails|messages|inbox)\b", low):
        inbox_id = settings.get("inbox_id")
        if not inbox_id:
            return {"message": "Set your default AgentMail inbox first.", "card": None}
        match = re.search(r"\bsearch(?:\s+(?:my\s+)?(?:email|emails|messages|inbox))?\s+(?:for\s+)?(.+)$", text, re.I)
        query = match.group(1).strip() if match else ""
        tool = _tool_name(info, "search_messages")
        return (tool, {"inboxId": inbox_id, "q": query}) if tool and query else None
    return None


def _filename(text: str) -> str | None:
    quoted = re.search(rf"[\"'`]([^\"'`\r\n]+\.(?:{_EXT_PATTERN}))[\"'`]", text, re.I)
    if quoted:
        return quoted.group(1).strip()
    match = re.search(rf"([\w][\w .()\-]*\.(?:{_EXT_PATTERN}))(?=$|[\s,;:!?]|\.(?:\s|$))", text, re.I)
    if not match:
        return None
    candidate = match.group(1).strip(" .?!\"'`")
    candidate = re.sub(
        r"^(?:please\s+)?(?:read|open|display|view|inspect|create|make|write|edit|update|append to|move|rename)\s+(?:(?:a|another|the)\s+)?(?:file\s+)?(?:called|named)?\s*",
        "",
        candidate,
        flags=re.I,
    )
    candidate = re.sub(r"^(?:please\s+)?show\s+me\s+(?:(?:information|info|details|metadata)\s+about\s+)?(?:the\s+)?", "", candidate, flags=re.I)
    candidate = re.sub(r"^(?:(?:information|info|details|metadata)\s+about\s+)(?:the\s+)?", "", candidate, flags=re.I)
    return candidate.strip(" .?!\"'`") or None


def _folder_name(text: str) -> str | None:
    match = re.search(
        r"\b(?:create|make)\s+(?:(?:a|another|the)\s+)?(?:folder|directory)\s+(?:called|named)\s+(.+?)(?=\s+(?:in|inside|under)\s+(?:the\s+)?(?:workspace|folder|directory)\b|[.!?]?$)",
        text,
        re.I,
    )
    if not match:
        return None
    value = match.group(1).strip().strip("\"'` .!?")
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        return None
    return value


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


def _mutation_request(text: str) -> bool:
    low = " ".join(text.lower().split())
    return bool(
        re.search(r"\b(?:create|make|write|edit|update|append|move|rename)\b", low)
        and (_filename(text) or _folder_name(text) or re.search(r"\b(?:file|folder|directory|workspace)\b", low))
    )


def _content_after_marker(text: str) -> str | None:
    match = re.search(r"\b(?:containing|with content|with the content|that says|saying)\s+(.+)$", text, re.I)
    if not match:
        return None
    return match.group(1).strip().strip("\"'`")


def _rename_target(text: str) -> str | None:
    match = re.search(rf"\b(?:to|as)\s+([\w][\w .()\-]*\.(?:{_EXT_PATTERN}))\b", text, re.I)
    return match.group(1).strip(" .?!\"'`") if match else None


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

    folder = _folder_name(text)
    if folder and root and re.search(r"\b(?:create|make)\b", low):
        tool = _tool_name(info, "create_directory")
        if tool:
            return tool, {"path": str(Path(root) / folder)}

    filename = _filename(text)
    if not filename:
        return None
    path = _join_root(root, filename)
    if not path:
        return None

    if re.search(r"\b(?:create|make|write)\b", low):
        tool = _tool_name(info, "write_file")
        content = _content_after_marker(text)
        if tool and content is not None:
            return tool, {"path": path, "content": content}

    if re.search(r"\b(?:move|rename)\b", low):
        tool = _tool_name(info, "move_file")
        target = _rename_target(text)
        if tool and target:
            destination = _join_root(root, target)
            if destination:
                return tool, {"source": path, "destination": destination}

    if re.search(r"\b(?:information|info|details|metadata|size|modified|created)\b", low):
        tool = _tool_name(info, "get_file_info")
        if tool:
            return tool, {"path": path}

    if re.search(r"\b(?:read|open|show|display|inspect|view)\b", low):
        tool = _tool_name(info, "read_text_file", "read_file")
        if tool:
            return tool, {"path": path}

    return None


async def _route_agentmail(text: str) -> dict[str, Any] | None:
    configured = _agentmail_config(text)
    if configured is not None:
        return configured
    if not _agentmail_intent(text):
        return None
    server = _agentmail_server()
    if not server:
        return {"message": "AgentMail is not registered yet. Add it from Plugins, then try the email request again.", "card": None}
    try:
        info = await inspect_server("agentmail")
    except Exception as exc:
        return {"message": f"AgentMail is registered but not connected: {_error_text(exc)}. Make sure AGENTMAIL_API_KEY is set and restart Agentie.", "card": None}
    choice = _agentmail_choice(text, info)
    if isinstance(choice, dict):
        return choice
    if not choice:
        return None
    tool_name, arguments = choice
    canonical = f"Call MCP agentmail tool {tool_name} with {json.dumps(arguments, ensure_ascii=False)}"
    approval = _approval_response("agentmail", tool_name, arguments, canonical, natural=True)
    if approval.get("approved"):
        try:
            return await execute_tool("agentmail", tool_name, arguments)
        except Exception as exc:
            return {"message": f"The approved AgentMail action could not complete: {_error_text(exc)}", "card": None}
    return approval


async def route_capability_preflight(message: str) -> dict[str, Any] | None:
    """Intercept high-confidence local capability requests before generic parsing.

    AgentMail email intents and explicit filesystem requests are handled here so
    they never fall through to a paid model when a dedicated local/MCP route exists.
    """
    text = " ".join(str(message or "").strip().split())
    if not text:
        return None

    agentmail = await _route_agentmail(text)
    if agentmail is not None:
        return agentmail

    if not (_filename(text) or _extension_search(text) or _allowed_directories_request(text) or _mutation_request(text)):
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
