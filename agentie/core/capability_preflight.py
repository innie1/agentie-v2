from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentie.core import agent_registry
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


def _agentmail_history_path() -> Path:
    return WORKSPACE / "agentmail_history.json"


def _load_agentmail_settings() -> dict[str, Any]:
    path = _agentmail_settings_path()
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _save_agentmail_settings(settings: dict[str, Any]) -> None:
    path = _agentmail_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_agentmail_history() -> list[dict[str, Any]]:
    path = _agentmail_history_path()
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except Exception:
        return []


def _save_agentmail_history(items: list[dict[str, Any]]) -> None:
    path = _agentmail_history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items[-500:], indent=2, ensure_ascii=False), encoding="utf-8")


def _agent_from_session(session_id: str | None) -> dict[str, Any] | None:
    match = re.match(r"^agent:(agt_[a-z0-9]+):", str(session_id or ""), re.I)
    return agent_registry.get_agent(match.group(1)) if match else None


def _scoped_agentmail_settings(session_id: str | None) -> dict[str, Any]:
    settings = _load_agentmail_settings()
    scoped = {key: value for key, value in settings.items() if key != "agents"}
    agent = _agent_from_session(session_id)
    if agent:
        agent_settings = (settings.get("agents") or {}).get(str(agent["id"]), {})
        if isinstance(agent_settings, dict):
            scoped.update(agent_settings)
    return scoped


def _set_scoped_agentmail_setting(session_id: str | None, key: str, value: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    settings = _load_agentmail_settings()
    agent = _agent_from_session(session_id)
    if agent:
        agents = settings.setdefault("agents", {})
        scoped = agents.setdefault(str(agent["id"]), {})
        scoped[key] = value
    else:
        settings[key] = value
    _save_agentmail_settings(settings)
    return settings, agent


def _email_address(text: str) -> str | None:
    match = re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", text, re.I)
    return match.group(0) if match else None


def _history_card(session_id: str | None) -> dict[str, Any]:
    agent = _agent_from_session(session_id)
    items = _load_agentmail_history()
    if agent:
        items = [item for item in items if str(item.get("agent_id") or "") == str(agent["id"])]
    items = items[-20:]
    lines = []
    for item in reversed(items):
        when = str(item.get("at") or "").replace("T", " ")[:19]
        action = str(item.get("action") or "email")
        subject = str(item.get("subject") or "").strip()
        other = item.get("to") or item.get("from") or item.get("inbox_id") or ""
        line = f"{when} · {action}"
        if subject:
            line += f" · {subject}"
        if other:
            line += f" · {other if isinstance(other, str) else ', '.join(map(str, other))}"
        routed = item.get("routed_agent") or {}
        if routed:
            line += f" → {routed.get('name')} ({routed.get('role')})"
        lines.append(line)
    title = f"Email · {agent['name']} history" if agent else "Email · History"
    return {
        "message": f"Here is {'this agent’s' if agent else 'local'} recent email history.",
        "card": {"type": "note", "title": title, "content": "\n".join(lines) if lines else "No email activity recorded yet."},
    }


def _agentmail_config(text: str, session_id: str | None = None) -> dict[str, Any] | None:
    compact = " ".join(str(text or "").strip().split())
    low = compact.lower().strip(" .?!")
    if low in {"show email history", "email history", "show my email history", "show agentmail history"}:
        return _history_card(session_id)

    email_match = re.match(r"^(?:set|save|remember)\s+(?:my\s+)?(?:notification|personal|destination)\s+email\s+(?:to|as)\s+(.+)$", compact, re.I)
    if email_match:
        address = _email_address(email_match.group(1))
        if not address:
            return {"message": "Please provide a valid email address.", "card": None}
        _, agent = _set_scoped_agentmail_setting(session_id, "notification_email", address)
        owner = f" for {agent['name']}" if agent else ""
        return {"message": f"Saved {address} as the AgentMail notification email{owner}.", "card": {"type": "note", "title": "AgentMail settings", "content": f"Notification email: {address}{owner}"}}

    inbox_match = re.match(r"^(?:set|save|remember)\s+(?:my\s+)?(?:agentmail\s+)?(?:sender\s+)?inbox(?:\s+id)?\s+(?:to|as)\s+([^\s]+)$", compact, re.I)
    if inbox_match:
        inbox_id = inbox_match.group(1).strip(" .?!\"'`")
        if not inbox_id:
            return {"message": "Please provide an AgentMail inbox ID.", "card": None}
        _, agent = _set_scoped_agentmail_setting(session_id, "inbox_id", inbox_id)
        owner = f" for {agent['name']}" if agent else ""
        return {"message": f"Saved the AgentMail sender inbox{owner}.", "card": {"type": "note", "title": "AgentMail settings", "content": f"Sender inbox: {inbox_id}{owner}"}}

    if low in {"show agentmail settings", "agentmail settings", "show my agentmail settings"}:
        settings = _scoped_agentmail_settings(session_id)
        agent = _agent_from_session(session_id)
        lines = [
            f"Scope: {agent['name']} ({agent['role']})" if agent else "Scope: default",
            f"Notification email: {settings.get('notification_email') or 'not set'}",
            f"Sender inbox: {settings.get('inbox_id') or 'not set'}",
        ]
        return {"message": "Here are the local AgentMail settings.", "card": {"type": "note", "title": "AgentMail settings", "content": "\n".join(lines)}}
    return None


def _agentmail_intent(text: str) -> bool:
    low = " ".join(str(text or "").lower().split())
    return bool(
        re.search(r"\b(?:email|e-mail|mail)\b", low)
        or "agentmail" in low
        or re.search(r"\b(?:inbox|inboxes|message|messages|thread|threads)\b", low)
        and re.search(r"\b(?:check|list|show|read|open|search|reply)\b", low)
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


def _agentmail_recipient(text: str, settings: dict[str, Any]) -> str | None:
    low = text.lower()
    if re.search(r"\b(?:email|mail|send(?: an?)? email)\s+me\b", low):
        return str(settings.get("notification_email") or "") or None
    return _email_address(text)


def _tool_name(info: dict[str, Any], *names: str) -> str | None:
    available = {str(item.get("name") or "").lower(): str(item.get("name") or "") for item in info.get("tools") or []}
    for name in names:
        if name.lower() in available:
            return available[name.lower()]
    return None


def _tool_schema(info: dict[str, Any], tool_name: str) -> dict[str, Any]:
    for item in info.get("tools") or []:
        if str(item.get("name") or "").lower() == str(tool_name or "").lower():
            schema = item.get("input_schema") or item.get("inputSchema") or {}
            return schema if isinstance(schema, dict) else {}
    return {}


def _supported_arguments(info: dict[str, Any], tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    schema = _tool_schema(info, tool_name)
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict) or not properties:
        return arguments
    return {key: value for key, value in arguments.items() if key in properties}


def _email_signature(agent: dict[str, Any] | None) -> str:
    if not agent:
        return ""
    name = str(agent.get("name") or "Agent").strip()
    role = str(agent.get("role") or "Agent").strip()
    role_line = role if re.search(r"\bAI\b", role, re.I) else f"AI {role} Agent"
    company = str(agent.get("company_identity") or "").strip()
    lines = ["—", name, role_line]
    if company:
        lines.append(company)
    return "\n".join(lines)


def _sign_email_body(body: str, agent: dict[str, Any] | None) -> str:
    text = str(body or "").strip()
    signature = _email_signature(agent)
    if not signature:
        return text
    name = str(agent.get("name") or "").strip()
    if name and name.casefold() in text[-250:].casefold() and re.search(r"\bAI\b", text[-250:], re.I):
        return text
    return f"{text}\n\n{signature}".strip()


def _message_or_thread_id(text: str) -> str | None:
    match = re.search(r"\b(?:email|message|thread)(?:\s+(?:id|#))?\s+([A-Za-z0-9._:-]{3,})\b", text, re.I)
    return match.group(1).strip() if match else None


def _search_query(text: str) -> str:
    match = re.search(r"\bsearch(?:\s+(?:my\s+)?(?:email|emails|messages|inbox|threads?))?\s+(?:for\s+)?(.+)$", text, re.I)
    return match.group(1).strip(" .?!\"'`") if match else ""


def _agentmail_choice(text: str, info: dict[str, Any], session_id: str | None = None) -> tuple[str, dict[str, Any]] | dict[str, Any] | None:
    low = " ".join(text.lower().split())
    settings = _scoped_agentmail_settings(session_id)
    agent = _agent_from_session(session_id)

    if re.search(r"\b(?:list|show|what are|check)\b.*\b(?:agentmail\s+)?inboxes\b", low) or low in {"agentmail inboxes", "list agentmail inboxes", "list my agentmail inboxes"}:
        tool = _tool_name(info, "list_inboxes")
        return (tool, _supported_arguments(info, tool, {"limit": 10})) if tool else None

    if re.search(r"\bsearch\b.*\b(?:email|emails|messages|inbox|threads?)\b", low):
        inbox_id = settings.get("inbox_id")
        if not inbox_id:
            return {"message": "Set your AgentMail inbox first.", "card": None}
        query = _search_query(text)
        if not query:
            return {"message": "What should I search for in the inbox?", "card": None}
        tool = _tool_name(info, "search_messages")
        if tool:
            return tool, _supported_arguments(info, tool, {"inboxId": inbox_id, "q": query, "query": query, "limit": 30})
        tool = _tool_name(info, "list_threads")
        if tool:
            args: dict[str, Any] = {"inboxId": inbox_id, "limit": 50}
            sender = re.search(r"\bfrom\s+(.+)$", query, re.I)
            recipient = re.search(r"\bto\s+(.+)$", query, re.I)
            if sender:
                args["senders"] = [sender.group(1).strip()]
            elif recipient:
                args["recipients"] = [recipient.group(1).strip()]
            else:
                args["subject"] = [query]
            return tool, _supported_arguments(info, tool, args)
        return None

    read_id = _message_or_thread_id(text) if re.search(r"\b(?:read|open|get|show)\b", low) else None
    if read_id:
        inbox_id = settings.get("inbox_id")
        if not inbox_id:
            return {"message": "Set your AgentMail inbox first.", "card": None}
        tool = _tool_name(info, "get_message", "read_message")
        if tool:
            return tool, _supported_arguments(info, tool, {"inboxId": inbox_id, "messageId": read_id, "id": read_id})
        tool = _tool_name(info, "get_thread")
        if tool:
            return tool, _supported_arguments(info, tool, {"inboxId": inbox_id, "threadId": read_id, "id": read_id})

    reply_match = re.search(r"\breply\s+to\s+(?:email|message|thread)(?:\s+(?:id|#))?\s+([A-Za-z0-9._:-]{3,})\s+(?:saying|with(?:\s+message)?|message|body)\s+(.+)$", text, re.I)
    if reply_match:
        inbox_id = settings.get("inbox_id")
        if not inbox_id:
            return {"message": "Set your AgentMail inbox first.", "card": None}
        tool = _tool_name(info, "reply_to_message", "reply_message")
        if not tool:
            return None
        body = _sign_email_body(reply_match.group(2).strip(" \"'`"), agent)
        args = {"inboxId": inbox_id, "messageId": reply_match.group(1), "text": body}
        return tool, _supported_arguments(info, tool, args)

    if re.search(r"\b(?:check|list|show|read)\b.*\b(?:email|emails|messages|inbox|threads?)\b", low):
        inbox_id = settings.get("inbox_id")
        if not inbox_id:
            return {"message": "I need your AgentMail inbox ID first. Say “List my AgentMail inboxes”, then “Set my AgentMail inbox to <inboxId>”.", "card": None}
        tool = _tool_name(info, "list_messages", "list_threads")
        if tool:
            return tool, _supported_arguments(info, tool, {"inboxId": inbox_id, "limit": 10})

    if re.match(r"^(?:please\s+)?(?:send(?:\s+an?)?\s+email|email|mail)\b", low):
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
        body = _sign_email_body(_agentmail_body(text) or "Message from Agentie.", agent)
        subject = _agentmail_subject(text) or "Agentie update"
        args = {"inboxId": inbox_id, "to": [recipient], "subject": subject, "text": body}
        return tool, _supported_arguments(info, tool, args)
    return None


def _parse_mcp_payload(result: dict[str, Any]) -> Any:
    card = result.get("card") if isinstance(result, dict) else None
    raw = str(card.get("content") or "") if isinstance(card, dict) else ""
    if not raw:
        return None
    for candidate in (raw, raw[raw.find("{"):] if "{" in raw else "", raw[raw.find("["):] if "[" in raw else ""):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return None


def _value(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, "", []):
            return value
    return None


def _address_text(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(_address_text(x) for x in value if x not in (None, ""))
    if isinstance(value, dict):
        return str(_value(value, "email", "address", "name") or "")
    return str(value or "")


def _routing_for_message(item: dict[str, Any]) -> dict[str, str] | None:
    text = str(_value(item, "subject", "text", "body", "preview", "snippet") or "").casefold()
    text += " " + _address_text(_value(item, "from", "sender", "fromAddress")).casefold()
    if not text.strip():
        return None
    agents = agent_registry.list_agents()
    scored = []
    domains = {
        "sales": {"sales", "outreach", "lead", "leads", "prospect", "customer", "client", "quote", "order", "pipeline"},
        "marketing": {"marketing", "content", "campaign", "social", "brand", "advert", "promotion"},
        "finance": {"finance", "account", "invoice", "payment", "budget", "cost", "expense", "revenue"},
        "research": {"research", "market", "competitor", "analysis", "evidence", "survey"},
        "operations": {"operations", "delivery", "logistics", "inventory", "schedule", "supplier", "fulfilment", "fulfillment"},
        "engineering": {"cto", "developer", "engineer", "coding", "software", "technical", "bug", "api", "database"},
    }
    words = set(re.findall(r"[a-z0-9]+", text))
    for agent in agents:
        profile = f"{agent.get('name','')} {agent.get('role','')} {agent.get('purpose','')} {agent.get('goal','')}".casefold()
        score = 0
        name = str(agent.get("name") or "").strip().casefold()
        if name and re.search(rf"\b{re.escape(name)}\b", text):
            score += 10
        profile_words = set(re.findall(r"[a-z0-9]+", profile))
        score += min(3, len(words & profile_words))
        for domain, terms in domains.items():
            if words & terms and (domain in profile or profile_words & terms):
                score += 4
        scored.append((score, agent))
    scored.sort(key=lambda row: (-row[0], str(row[1].get("name") or "").casefold()))
    if not scored or scored[0][0] < 4:
        return None
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return None
    agent = scored[0][1]
    return {"id": str(agent.get("id") or ""), "name": str(agent.get("name") or ""), "role": str(agent.get("role") or "")}


def _collect_email_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("messages", "threads", "inboxes", "items", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    if isinstance(payload.get("thread"), dict):
        thread = payload["thread"]
        if isinstance(thread.get("messages"), list):
            return [x for x in thread["messages"] if isinstance(x, dict)]
        return [thread]
    if any(key in payload for key in ("messageId", "threadId", "inboxId", "subject")):
        return [payload]
    return []


def _email_note(tool_name: str, payload: Any, arguments: dict[str, Any]) -> tuple[str, str, dict[str, str] | None]:
    tool = str(tool_name or "").lower()
    items = _collect_email_items(payload)
    routed_first = None
    lines: list[str] = []
    if tool == "list_inboxes":
        for item in items[:20]:
            email = _address_text(_value(item, "email", "address"))
            display = str(_value(item, "displayName", "name") or "").strip()
            inbox_id = str(_value(item, "inboxId", "id") or "").strip()
            lines.append(f"{display + ' · ' if display else ''}{email or 'Inbox'}" + (f"\nInbox ID: {inbox_id}" if inbox_id else ""))
        return "Email · Inboxes", "\n\n".join(lines) or "No inboxes returned.", None

    for item in items[:20]:
        subject = str(_value(item, "subject", "title") or "(no subject)").strip()
        sender = _address_text(_value(item, "from", "sender", "fromAddress"))
        date = str(_value(item, "createdAt", "sentAt", "receivedAt", "date", "updatedAt") or "").replace("T", " ")[:19]
        ident = str(_value(item, "messageId", "threadId", "id") or "").strip()
        preview = str(_value(item, "preview", "snippet", "text", "body") or "").strip().replace("\n", " ")
        if len(preview) > 220:
            preview = preview[:217].rstrip() + "..."
        route = _routing_for_message(item)
        if route and not routed_first:
            routed_first = route
        meta = " · ".join(x for x in (f"From: {sender}" if sender else "", date, f"ID: {ident}" if ident else "") if x)
        block = subject + (f"\n{meta}" if meta else "")
        if preview:
            block += f"\n{preview}"
        if route:
            block += f"\n→ Routed to {route['name']} ({route['role']})"
        lines.append(block)

    if tool in {"send_message", "reply_to_message", "reply_message", "forward_message", "send_draft"}:
        title = "Email · Sent"
        if not lines:
            subject = str(arguments.get("subject") or "Email")
            recipients = _address_text(arguments.get("to"))
            lines = [subject + (f"\nTo: {recipients}" if recipients else "") + "\nSent through AgentMail."]
    elif "search" in tool:
        title = "Email · Search"
    elif tool in {"get_message", "read_message", "get_thread"}:
        title = "Email · Message"
    else:
        title = "Email · Inbox"
    return title, "\n\n".join(lines) or "AgentMail completed without a structured message list.", routed_first


def _record_email_history(tool_name: str, arguments: dict[str, Any], session_id: str | None, payload: Any, routed: dict[str, str] | None = None) -> None:
    agent = _agent_from_session(session_id)
    items = _collect_email_items(payload)
    first = items[0] if items else {}
    row = {
        "at": datetime.now(timezone.utc).isoformat(),
        "action": str(tool_name or ""),
        "agent_id": agent.get("id") if agent else None,
        "agent_name": agent.get("name") if agent else None,
        "inbox_id": arguments.get("inboxId"),
        "subject": arguments.get("subject") or _value(first, "subject", "title"),
        "to": arguments.get("to"),
        "from": _address_text(_value(first, "from", "sender", "fromAddress")) or None,
        "message_id": arguments.get("messageId") or _value(first, "messageId", "id"),
        "thread_id": arguments.get("threadId") or _value(first, "threadId"),
        "routed_agent": routed,
    }
    items_history = _load_agentmail_history()
    items_history.append({key: value for key, value in row.items() if value not in (None, "", [], {})})
    _save_agentmail_history(items_history)


def finalize_agentmail_result(tool_name: str, arguments: dict[str, Any], result: dict[str, Any], session_id: str | None = None) -> dict[str, Any]:
    payload = _parse_mcp_payload(result)
    title, content, routed = _email_note(tool_name, payload, arguments)
    _record_email_history(tool_name, arguments, session_id, payload, routed)
    if payload is None:
        return result
    return {
        "message": f"AgentMail {str(tool_name).replace('_', ' ')} completed.",
        "card": {"type": "note", "title": title, "content": content},
    }


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
        "", candidate, flags=re.I,
    )
    candidate = re.sub(r"^(?:please\s+)?show\s+me\s+(?:(?:information|info|details|metadata)\s+about\s+)?(?:the\s+)?", "", candidate, flags=re.I)
    candidate = re.sub(r"^(?:(?:information|info|details|metadata)\s+about\s+)(?:the\s+)?", "", candidate, flags=re.I)
    return candidate.strip(" .?!\"'`") or None


def _folder_name(text: str) -> str | None:
    match = re.search(
        r"\b(?:create|make)\s+(?:(?:a|another|the)\s+)?(?:folder|directory)\s+(?:called|named)\s+(.+?)(?=\s+(?:in|inside|under)\s+(?:the\s+)?(?:workspace|folder|directory)\b|[.!?]?$)",
        text, re.I,
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


async def _route_agentmail(text: str, session_id: str | None = None) -> dict[str, Any] | None:
    configured = _agentmail_config(text, session_id)
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
    choice = _agentmail_choice(text, info, session_id)
    if isinstance(choice, dict):
        return choice
    if not choice:
        return None
    tool_name, arguments = choice
    canonical = f"Call MCP agentmail tool {tool_name} with {json.dumps(arguments, ensure_ascii=False)}"
    approval = _approval_response("agentmail", tool_name, arguments, canonical, natural=True)
    if approval.get("approved"):
        try:
            result = await execute_tool("agentmail", tool_name, arguments)
            return finalize_agentmail_result(tool_name, arguments, result, session_id)
        except Exception as exc:
            return {"message": f"The approved AgentMail action could not complete: {_error_text(exc)}", "card": None}
    return approval


async def route_capability_preflight(message: str, session_id: str | None = None) -> dict[str, Any] | None:
    """Intercept high-confidence local capability requests before generic parsing."""
    text = " ".join(str(message or "").strip().split())
    if not text:
        return None
    agentmail = await _route_agentmail(text, session_id)
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
