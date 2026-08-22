from __future__ import annotations

import json
import re
from typing import Any

from agentie.core import agent_registry
from agentie.core.mcp_client import _approval_response, _error_text, execute_tool, inspect_server, list_servers
from agentie.core.plugin_credentials import setup_response
from agentie.core.whatsapp_cloud import (
    assign_contact,
    get_message,
    list_messages,
    set_support_agent,
    set_support_mode,
    settings_snapshot,
    sign_agent_message,
)


def _agent_from_session(session_id: str | None) -> dict[str, Any] | None:
    match = re.match(r"^agent:(agt_[a-z0-9]+):", str(session_id or ""), re.I)
    return agent_registry.get_agent(match.group(1)) if match else None


def _server_registered() -> bool:
    return any(str(item.get("name") or "").lower() == "whatsapp" for item in list_servers())


def _phone(text: str) -> str | None:
    match = re.search(r"(?<!\w)(\+?\d[\d\s().-]{6,}\d)(?!\w)", text)
    return match.group(1).strip() if match else None


def _body(text: str) -> str:
    patterns = (
        r"\b(?:saying|that says|message|body|text)\s*[:=-]?\s*(.+)$",
        r"\bwith\s+(?:the\s+)?(?:message|body|text)\s*[:=-]?\s*(.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(1).strip(" .\"'`")
    return ""


def _message_id(text: str) -> str | None:
    match = re.search(r"\b(?:whatsapp\s+)?message(?:\s+(?:id|#))?\s+([A-Za-z0-9._:-]{5,})\b", text, re.I)
    return match.group(1) if match else None


def _latest_incoming() -> dict[str, Any] | None:
    items = list_messages(limit=50, direction="incoming")
    return items[0] if items else None


def _settings_card() -> dict[str, Any]:
    settings = settings_snapshot();support = settings.get("support_agent") or {}
    lines = [
        f"Support mode: {'on' if settings.get('support_mode') else 'off'}",
        f"Support agent: {support.get('name') or 'automatic'}",
    ]
    contacts = settings.get("contacts") or []
    if contacts:
        lines.append("Contact routing:")
        for item in contacts[:30]:
            agent = item.get("agent") or {}
            lines.append(f"- {item.get('phone')} → {agent.get('name') or 'unassigned'}")
    return {"message":"Here are the WhatsApp support settings.","card":{"type":"note","title":"WhatsApp · Settings","content":"\n".join(lines)}}


def _history_card(*, needs_human: bool | None = None, limit: int = 20) -> dict[str, Any]:
    items = list_messages(limit=limit, needs_human=needs_human)
    lines = []
    for item in items:
        direction = "←" if item.get("direction") == "incoming" else "→"
        other = item.get("from") if item.get("direction") == "incoming" else item.get("to")
        who = item.get("profile_name") or other or "unknown"
        body = str(item.get("body") or "").replace("\n", " ")[:180]
        route = item.get("routed_agent_name") or item.get("agent_name") or ""
        human = f" · HUMAN: {item.get('escalation_reason') or 'yes'}" if item.get("needs_human") else ""
        lines.append(f"{direction} {who} · {body}{f' · {route}' if route else ''}{human}")
    title = "WhatsApp · Needs human" if needs_human else "WhatsApp · Recent messages"
    message = "Here are WhatsApp conversations that need human attention." if needs_human else "Here are the recent WhatsApp conversations."
    return {"message":message,"card":{"type":"note","title":title,"content":"\n".join(lines) if lines else "No matching WhatsApp messages yet."}}


def _config_command(text: str) -> dict[str, Any] | None:
    compact = " ".join(str(text or "").strip().split());low = compact.lower().strip(" .?!")
    if low in {"show whatsapp settings","whatsapp settings","show my whatsapp settings"}:
        return _settings_card()
    if low in {"show whatsapp history","whatsapp history","show whatsapp messages","check whatsapp","check my whatsapp"}:
        return _history_card()
    if re.search(r"\b(?:show|list|check)\b.*\bwhatsapp\b.*\b(?:need|needs|needing)\s+human\b", low):
        return _history_card(needs_human=True)
    match = re.match(r"^(?:set|assign)\s+(?:the\s+)?whatsapp\s+support\s+agent\s+(?:to|as)\s+(.+)$", compact, re.I)
    if match:
        try:
            state = set_support_agent(match.group(1).strip())
        except ValueError as exc:
            return {"message":str(exc),"card":None}
        support = state.get("support_agent") or {}
        return {"message":f"WhatsApp support messages will route to {support.get('name') or 'the selected agent'}.","card":{"type":"note","title":"WhatsApp · Support agent","content":f"Support agent: {support.get('name')} ({support.get('role')})"}}
    if re.match(r"^(?:enable|turn on)\s+whatsapp\s+support\s+mode$", compact, re.I):
        set_support_mode(True);return {"message":"WhatsApp support mode is enabled.","card":{"type":"note","title":"WhatsApp · Support mode","content":"Enabled"}}
    if re.match(r"^(?:disable|turn off)\s+whatsapp\s+support\s+mode$", compact, re.I):
        set_support_mode(False);return {"message":"WhatsApp support mode is disabled.","card":{"type":"note","title":"WhatsApp · Support mode","content":"Disabled"}}
    match = re.match(r"^(?:assign|route)\s+whatsapp\s+contact\s+(.+?)\s+(?:to|through)\s+(.+)$", compact, re.I)
    if match:
        try:
            state = assign_contact(match.group(1).strip(), match.group(2).strip())
        except ValueError as exc:
            return {"message":str(exc),"card":None}
        return {"message":"Saved the WhatsApp contact routing.","card":{"type":"note","title":"WhatsApp · Contact routing","content":json.dumps(state.get('contacts') or [],ensure_ascii=False,indent=2)}}
    return None


def _intent(text: str) -> bool:
    low = str(text or "").lower()
    return "whatsapp" in low and bool(re.search(r"\b(?:check|show|list|read|open|search|find|send|reply|message|messages|template|mark|history|support|assign|route|enable|disable)\b", low))


def _tool_names(info: dict[str, Any]) -> set[str]:
    return {str(item.get("name") or "") for item in info.get("tools") or [] if item.get("name")}


def _tool(info: dict[str, Any], *names: str) -> str | None:
    available = {name.lower(): name for name in _tool_names(info)}
    return next((available[name.lower()] for name in names if name.lower() in available), None)


async def route_whatsapp(message: str, session_id: str | None = None) -> dict[str, Any] | None:
    text = " ".join(str(message or "").strip().split())
    if not text or "whatsapp" not in text.lower():
        return None
    configured = _config_command(text)
    if configured is not None:
        return configured
    if not _intent(text):
        return None
    if not _server_registered():
        return {"message":"WhatsApp Cloud is not registered yet. Add it from Plugins, configure the Meta credentials, then try again.","card":None}
    try:
        info = await inspect_server("whatsapp")
    except Exception as exc:
        return setup_response("whatsapp", _error_text(exc))

    low = text.lower();agent = _agent_from_session(session_id)

    if re.search(r"\b(?:show|list|check|read)\b.*\bwhatsapp\b.*\b(?:messages?|history|inbox|conversations?)\b", low):
        return _history_card()

    if re.search(r"\b(?:show|list|check)\b.*\b(?:need|needs|needing)\s+human\b", low):
        return _history_card(needs_human=True)

    if re.search(r"\bmark\b.*\bwhatsapp\b.*\bread\b", low):
        message_id = _message_id(text)
        if not message_id:
            return {"message":"Tell me which WhatsApp message ID to mark as read.","card":None}
        tool = _tool(info, "mark_whatsapp_read")
        if not tool:return {"message":"The WhatsApp MCP does not expose a mark-read tool.","card":None}
        try:return await execute_tool("whatsapp", tool, {"message_id":message_id})
        except Exception as exc:return {"message":f"Could not mark that WhatsApp message as read: {_error_text(exc)}","card":None}

    template_match = re.search(r"\b(?:send\s+)?whatsapp\s+template\s+([A-Za-z0-9_]+)\s+to\s+(.+?)(?:\s+language\s+([A-Za-z_-]+))?$", text, re.I)
    if template_match:
        tool = _tool(info, "send_whatsapp_template")
        if not tool:return {"message":"The WhatsApp MCP does not expose template sending.","card":None}
        recipient = _phone(template_match.group(2))
        if not recipient:return {"message":"Provide the customer's full international WhatsApp number.","card":None}
        arguments = {"to":recipient,"template_name":template_match.group(1),"language_code":template_match.group(3) or "en_US","components_json":"[]"}
        canonical = f"Call MCP whatsapp tool {tool} with {json.dumps(arguments,ensure_ascii=False)}"
        approval = _approval_response("whatsapp",tool,arguments,canonical,natural=True)
        if approval.get("approved"):
            try:return await execute_tool("whatsapp",tool,arguments)
            except Exception as exc:return {"message":f"The approved WhatsApp template could not send: {_error_text(exc)}","card":None}
        if isinstance(approval.get("card"),dict):approval["card"]["command"]=text
        return approval

    reply_match = re.search(r"\breply\s+(?:to\s+)?(?:the\s+)?(?:latest\s+)?whatsapp(?:\s+message)?(?:\s+(?:id|#)?\s*([A-Za-z0-9._:-]{5,}))?\s+(?:saying|message|with(?:\s+the)?\s+message)\s+(.+)$", text, re.I)
    if reply_match:
        message_id = reply_match.group(1)
        source = get_message(message_id) if message_id else _latest_incoming()
        if not source or source.get("direction") != "incoming":
            return {"message":"I couldn't find that incoming WhatsApp message to reply to.","card":None}
        recipient = str(source.get("from") or "")
        body = sign_agent_message(reply_match.group(2).strip(" .\"'`"), agent)
        tool = _tool(info, "send_whatsapp_text")
        if not tool:return {"message":"The WhatsApp MCP does not expose text sending.","card":None}
        arguments = {"to":recipient,"text":body}
        canonical = f"Call MCP whatsapp tool {tool} with {json.dumps(arguments,ensure_ascii=False)}"
        approval = _approval_response("whatsapp",tool,arguments,canonical,natural=True)
        if approval.get("approved"):
            try:return await execute_tool("whatsapp",tool,arguments)
            except Exception as exc:return {"message":f"The approved WhatsApp reply could not send: {_error_text(exc)}","card":None}
        if isinstance(approval.get("card"),dict):approval["card"]["command"]=text
        return approval

    if re.search(r"\b(?:send\s+)?whatsapp\b", low):
        recipient = _phone(text);body = _body(text)
        if not recipient:return {"message":"Tell me the customer's full international WhatsApp number, for example +2348012345678.","card":None}
        if not body:return {"message":"What should the WhatsApp message say?","card":None}
        tool = _tool(info, "send_whatsapp_text")
        if not tool:return {"message":"The WhatsApp MCP does not expose text sending.","card":None}
        arguments = {"to":recipient,"text":sign_agent_message(body,agent)}
        canonical = f"Call MCP whatsapp tool {tool} with {json.dumps(arguments,ensure_ascii=False)}"
        approval = _approval_response("whatsapp",tool,arguments,canonical,natural=True)
        if approval.get("approved"):
            try:return await execute_tool("whatsapp",tool,arguments)
            except Exception as exc:return {"message":f"The approved WhatsApp message could not send: {_error_text(exc)}","card":None}
        if isinstance(approval.get("card"),dict):approval["card"]["command"]=text
        return approval

    return _history_card()
