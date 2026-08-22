from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

WORKSPACE = Path.cwd() / "workspace"
HISTORY_FILE = WORKSPACE / "whatsapp_history.json"
SETTINGS_FILE = WORKSPACE / "whatsapp_settings.json"
EVENTS_FILE = WORKSPACE / "whatsapp_events.json"


def _load_json(path: Path, default: Any) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
        return value
    except Exception:
        return default


def _save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _iso_from_unix(value: Any) -> str:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    except Exception:
        return _now()


def _credentials() -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        from agentie.core.plugin_credentials import server_environment
        values.update(server_environment("whatsapp"))
    except Exception:
        pass
    for name in (
        "WHATSAPP_ACCESS_TOKEN",
        "WHATSAPP_PHONE_NUMBER_ID",
        "WHATSAPP_VERIFY_TOKEN",
        "WHATSAPP_APP_SECRET",
        "WHATSAPP_GRAPH_VERSION",
    ):
        if not values.get(name) and os.environ.get(name):
            values[name] = str(os.environ[name])
    return values


def connection_state() -> dict[str, Any]:
    cfg = _credentials()
    required = (
        "WHATSAPP_ACCESS_TOKEN",
        "WHATSAPP_PHONE_NUMBER_ID",
        "WHATSAPP_VERIFY_TOKEN",
        "WHATSAPP_APP_SECRET",
    )
    missing = [name for name in required if not cfg.get(name)]
    return {
        "configured": not missing,
        "missing": missing,
        "phone_number_id_configured": bool(cfg.get("WHATSAPP_PHONE_NUMBER_ID")),
        "webhook_security_configured": bool(cfg.get("WHATSAPP_VERIFY_TOKEN") and cfg.get("WHATSAPP_APP_SECRET")),
        "graph_version": cfg.get("WHATSAPP_GRAPH_VERSION") or "v23.0",
    }


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if not 8 <= len(digits) <= 15:
        raise ValueError("Use a full international WhatsApp number, for example +2348012345678.")
    return digits


def _graph_url() -> str:
    cfg = _credentials()
    phone_id = str(cfg.get("WHATSAPP_PHONE_NUMBER_ID") or "").strip()
    token = str(cfg.get("WHATSAPP_ACCESS_TOKEN") or "").strip()
    if not phone_id or not token:
        raise ValueError("WhatsApp Cloud API needs WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID.")
    version = str(cfg.get("WHATSAPP_GRAPH_VERSION") or "v23.0").strip()
    if not re.fullmatch(r"v\d+(?:\.\d+)?", version):
        version = "v23.0"
    return f"https://graph.facebook.com/{version}/{phone_id}/messages"


def _graph_post(payload: dict[str, Any]) -> dict[str, Any]:
    cfg = _credentials()
    token = str(cfg.get("WHATSAPP_ACCESS_TOKEN") or "").strip()
    if not token:
        raise ValueError("WhatsApp Cloud API access token is not configured.")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        _graph_url(),
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Agentie-WhatsApp/1.0",
        },
    )
    try:
        with urlopen(request, timeout=25) as response:
            raw = response.read().decode("utf-8", errors="replace")
            value = json.loads(raw or "{}")
            return value if isinstance(value, dict) else {"result": value}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")[:3000]
        try:
            parsed = json.loads(raw)
            detail = str(((parsed.get("error") or {}).get("message") or raw))
        except Exception:
            detail = raw or str(exc)
        raise RuntimeError(f"WhatsApp Cloud API returned HTTP {exc.code}: {detail[:700]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach the WhatsApp Cloud API: {exc.reason}") from exc


def _load_history() -> list[dict[str, Any]]:
    value = _load_json(HISTORY_FILE, [])
    return value if isinstance(value, list) else []


def _save_history(items: list[dict[str, Any]]) -> None:
    _save_json(HISTORY_FILE, items[-1500:])


def _record(item: dict[str, Any]) -> dict[str, Any]:
    items = _load_history()
    message_id = str(item.get("id") or "")
    if message_id:
        existing = next((x for x in items if str(x.get("id") or "") == message_id), None)
        if existing:
            existing.update({k: v for k, v in item.items() if v is not None})
            _save_history(items)
            return existing
    items.append(item)
    _save_history(items)
    return item


def list_messages(
    limit: int = 20,
    phone: str | None = None,
    direction: str | None = None,
    needs_human: bool | None = None,
) -> list[dict[str, Any]]:
    items = _load_history()
    if phone:
        needle = normalize_phone(phone)
        items = [x for x in items if str(x.get("from") or x.get("to") or "") == needle]
    if direction:
        wanted = str(direction).strip().lower()
        items = [x for x in items if str(x.get("direction") or "").lower() == wanted]
    if needs_human is not None:
        items = [x for x in items if bool(x.get("needs_human")) is bool(needs_human)]
    return list(reversed(items[-max(1, min(int(limit or 20), 100)):]))


def get_message(message_id: str) -> dict[str, Any] | None:
    key = str(message_id or "").strip()
    return next((x for x in reversed(_load_history()) if str(x.get("id") or "") == key), None)


def _agent_signature(agent: dict[str, Any] | None) -> str:
    if not agent:
        return ""
    name = str(agent.get("name") or "Agent").strip()
    role = str(agent.get("role") or "Agent").strip()
    role_line = role if re.search(r"\bAI\b", role, re.I) else f"AI {role} Agent"
    company = str(agent.get("company_identity") or "").strip()
    signature = f"— {name} · {role_line}"
    if company:
        signature += f"\n{company}"
    return signature


def sign_agent_message(text: str, agent: dict[str, Any] | None) -> str:
    body = str(text or "").strip()
    signature = _agent_signature(agent)
    if not signature:
        return body
    name = str((agent or {}).get("name") or "").strip()
    if name and name.casefold() in body[-220:].casefold() and "ai" in body[-220:].casefold():
        return body
    return f"{body}\n\n{signature}".strip()


def send_text_message(to: str, text: str, *, agent: dict[str, Any] | None = None) -> dict[str, Any]:
    recipient = normalize_phone(to)
    body = sign_agent_message(text, agent)
    if not body:
        raise ValueError("WhatsApp message text is required.")
    if len(body) > 4096:
        raise ValueError("WhatsApp text messages must be 4096 characters or fewer.")
    result = _graph_post({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "text",
        "text": {"preview_url": False, "body": body},
    })
    message_id = str(((result.get("messages") or [{}])[0] or {}).get("id") or "")
    item = _record({
        "id": message_id or f"local-{hashlib.sha256((recipient + body + _now()).encode()).hexdigest()[:16]}",
        "direction": "outgoing",
        "to": recipient,
        "from": None,
        "type": "text",
        "body": body,
        "status": "accepted",
        "at": _now(),
        "agent_id": (agent or {}).get("id"),
        "agent_name": (agent or {}).get("name"),
        "needs_human": False,
    })
    return {"sent": True, "message": item, "provider": result}


def send_template_message(
    to: str,
    template_name: str,
    language_code: str = "en_US",
    components: list[dict[str, Any]] | None = None,
    *,
    agent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    recipient = normalize_phone(to)
    name = str(template_name or "").strip()
    language = str(language_code or "en_US").strip()
    if not re.fullmatch(r"[a-z0-9_]{1,512}", name, re.I):
        raise ValueError("Provide a valid approved WhatsApp template name.")
    template: dict[str, Any] = {"name": name, "language": {"code": language}}
    if components:
        template["components"] = components
    result = _graph_post({
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "template",
        "template": template,
    })
    message_id = str(((result.get("messages") or [{}])[0] or {}).get("id") or "")
    item = _record({
        "id": message_id or f"local-{hashlib.sha256((recipient + name + _now()).encode()).hexdigest()[:16]}",
        "direction": "outgoing",
        "to": recipient,
        "type": "template",
        "template_name": name,
        "body": f"Template: {name}",
        "status": "accepted",
        "at": _now(),
        "agent_id": (agent or {}).get("id"),
        "agent_name": (agent or {}).get("name"),
        "needs_human": False,
    })
    return {"sent": True, "message": item, "provider": result}


def mark_message_read(message_id: str) -> dict[str, Any]:
    key = str(message_id or "").strip()
    if not key:
        raise ValueError("WhatsApp message ID is required.")
    result = _graph_post({
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": key,
    })
    item = get_message(key)
    if item:
        item["read"] = True
        _record(item)
    return {"marked_read": True, "message_id": key, "provider": result}


def _load_settings() -> dict[str, Any]:
    value = _load_json(SETTINGS_FILE, {})
    return value if isinstance(value, dict) else {}


def _save_settings(value: dict[str, Any]) -> None:
    _save_json(SETTINGS_FILE, value)


def _find_agent(agent_id_or_name: str) -> dict[str, Any] | None:
    try:
        from agentie.core.agent_registry import get_agent
        return get_agent(agent_id_or_name)
    except Exception:
        return None


def set_support_agent(agent_id_or_name: str | None) -> dict[str, Any]:
    settings = _load_settings()
    if not agent_id_or_name:
        settings.pop("support_agent_id", None)
        _save_settings(settings)
        return settings_snapshot()
    agent = _find_agent(agent_id_or_name)
    if not agent:
        raise ValueError("Agent was not found.")
    settings["support_agent_id"] = agent["id"]
    settings["support_mode"] = True
    _save_settings(settings)
    return settings_snapshot()


def set_support_mode(enabled: bool) -> dict[str, Any]:
    settings = _load_settings();settings["support_mode"] = bool(enabled);_save_settings(settings);return settings_snapshot()


def assign_contact(phone: str, agent_id_or_name: str | None) -> dict[str, Any]:
    number = normalize_phone(phone)
    settings = _load_settings();contacts = settings.setdefault("contacts", {})
    if not agent_id_or_name:
        contacts.pop(number, None)
    else:
        agent = _find_agent(agent_id_or_name)
        if not agent:
            raise ValueError("Agent was not found.")
        contacts[number] = agent["id"]
    _save_settings(settings)
    return settings_snapshot()


def settings_snapshot() -> dict[str, Any]:
    settings = _load_settings();support = _find_agent(str(settings.get("support_agent_id") or "")) if settings.get("support_agent_id") else None
    contacts = []
    for phone, agent_id in (settings.get("contacts") or {}).items():
        agent = _find_agent(str(agent_id))
        contacts.append({"phone": phone, "agent": agent})
    return {
        "support_mode": bool(settings.get("support_mode", True)),
        "support_agent": support,
        "contacts": contacts,
    }


def _default_route_agent() -> dict[str, Any] | None:
    try:
        from agentie.core.agent_registry import list_agents
        agents = list_agents()
    except Exception:
        return None
    for pattern in (r"chief of staff", r"customer support|customer service|support", r"manager", r"ceo"):
        for agent in agents:
            hay = f"{agent.get('name','')} {agent.get('role','')}".lower()
            if re.search(pattern, hay, re.I):
                return agent
    return agents[0] if agents else None


def route_incoming_agent(phone: str, body: str = "") -> dict[str, Any] | None:
    settings = _load_settings();number = normalize_phone(phone)
    assigned = (settings.get("contacts") or {}).get(number)
    if assigned:
        agent = _find_agent(str(assigned))
        if agent:
            return agent
    if settings.get("support_agent_id"):
        agent = _find_agent(str(settings.get("support_agent_id")))
        if agent:
            return agent
    return _default_route_agent()


def escalation_reason(body: str) -> str | None:
    text = str(body or "").lower()
    checks = (
        (r"\b(?:human|real person|person|manager|supervisor|someone human)\b", "Customer requested a human"),
        (r"\b(?:refund|chargeback|fraud|scam|unauthori[sz]ed charge|payment dispute)\b", "Payment/refund dispute"),
        (r"\b(?:lawyer|legal action|sue|police|regulator)\b", "Legal or regulatory issue"),
        (r"\b(?:emergency|urgent safety|danger|threat)\b", "Urgent safety issue"),
    )
    for pattern, label in checks:
        if re.search(pattern, text, re.I):
            return label
    return None


def _message_body(message: dict[str, Any]) -> str:
    kind = str(message.get("type") or "unknown")
    if kind == "text":
        return str((message.get("text") or {}).get("body") or "")
    if kind == "button":
        return str((message.get("button") or {}).get("text") or "")
    if kind == "interactive":
        interactive = message.get("interactive") or {}
        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
        return str(reply.get("title") or reply.get("id") or "")
    media = message.get(kind) if isinstance(message.get(kind), dict) else {}
    caption = str(media.get("caption") or "")
    return caption or f"[{kind} message]"


def _queue_event(item: dict[str, Any]) -> None:
    events = _load_json(EVENTS_FILE, [])
    if not isinstance(events, list):
        events = []
    events.append({"created_at": _now(), "delivered": False, "message": item})
    _save_json(EVENTS_FILE, events[-300:])


def ingest_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    received = 0;statuses = 0;duplicates = 0
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            if str(change.get("field") or "") != "messages":
                continue
            value = change.get("value") or {}
            metadata = value.get("metadata") or {}
            contacts = {str(x.get("wa_id") or ""): str((x.get("profile") or {}).get("name") or "") for x in value.get("contacts") or []}
            for status in value.get("statuses") or []:
                message_id = str(status.get("id") or "")
                if not message_id:
                    continue
                item = get_message(message_id) or {"id": message_id, "direction": "outgoing"}
                item["status"] = str(status.get("status") or item.get("status") or "")
                item["status_at"] = _iso_from_unix(status.get("timestamp"))
                if status.get("errors"):
                    item["status_errors"] = status.get("errors")
                _record(item);statuses += 1
            for message in value.get("messages") or []:
                message_id = str(message.get("id") or "")
                if message_id and get_message(message_id):
                    duplicates += 1
                    continue
                sender = normalize_phone(str(message.get("from") or ""))
                body = _message_body(message)
                routed = route_incoming_agent(sender, body)
                reason = escalation_reason(body)
                item = _record({
                    "id": message_id or f"webhook-{hashlib.sha256(json.dumps(message,sort_keys=True).encode()).hexdigest()[:16]}",
                    "direction": "incoming",
                    "from": sender,
                    "to": str(metadata.get("display_phone_number") or ""),
                    "phone_number_id": str(metadata.get("phone_number_id") or ""),
                    "profile_name": contacts.get(sender) or "",
                    "type": str(message.get("type") or "unknown"),
                    "body": body,
                    "at": _iso_from_unix(message.get("timestamp")),
                    "routed_agent_id": (routed or {}).get("id"),
                    "routed_agent_name": (routed or {}).get("name"),
                    "routed_agent_role": (routed or {}).get("role"),
                    "needs_human": bool(reason),
                    "escalation_reason": reason,
                    "read": False,
                })
                _queue_event(item);received += 1
    return {"received": received, "statuses": statuses, "duplicates": duplicates}


def verify_webhook_challenge(mode: str | None, verify_token: str | None, challenge: str | None) -> str | None:
    cfg = _credentials();expected = str(cfg.get("WHATSAPP_VERIFY_TOKEN") or "")
    if mode == "subscribe" and expected and hmac.compare_digest(str(verify_token or ""), expected):
        return str(challenge or "")
    return None


def verify_webhook_signature(raw_body: bytes, signature_header: str | None) -> bool:
    secret = str(_credentials().get("WHATSAPP_APP_SECRET") or "")
    if not secret:
        return False
    header = str(signature_header or "")
    if not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[7:], expected)


def poll_events(limit: int = 20) -> list[dict[str, Any]]:
    events = _load_json(EVENTS_FILE, [])
    if not isinstance(events, list):
        return []
    pending = [x for x in events if not x.get("delivered")][:max(1, min(int(limit or 20), 50))]
    if not pending:
        return []
    pending_ids = {id(x) for x in pending}
    for item in events:
        if id(item) in pending_ids:
            item["delivered"] = True
    _save_json(EVENTS_FILE, events[-300:])
    output = []
    for event in pending:
        item = event.get("message") or {}
        who = item.get("profile_name") or item.get("from") or "Unknown contact"
        route = item.get("routed_agent_name") or "unassigned"
        lines = [f"From: {who}", f"Routed to: {route}", str(item.get("body") or "")]
        if item.get("needs_human"):
            lines.append(f"Needs human: {item.get('escalation_reason') or 'yes'}")
        output.append({
            "message": f"New WhatsApp message from {who}.",
            "card": {"type": "note", "title": "WhatsApp · Incoming", "content": "\n".join(lines)},
        })
    return output
