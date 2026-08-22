from __future__ import annotations

import os,re
from typing import Any

from agentie.core.automation_events import publish_event

# Native sources are events Agentie can emit itself today. Webhook events let
# connected services/plugins deliver other real external events without adding a
# second scheduler or pretending an unavailable integration is connected.
_NATIVE={
    "file.uploaded":"File uploaded to Agentie",
    "whatsapp.message.received":"Incoming WhatsApp Cloud API message",
    "plugin.tool.completed":"Connected plugin/MCP tool completed",
}
_ALIASES={
    "file upload":"file.uploaded","file uploaded":"file.uploaded","new file":"file.uploaded",
    "whatsapp message":"whatsapp.message.received","incoming whatsapp message":"whatsapp.message.received",
    "email":"email.received","email arrives":"email.received","incoming email":"email.received","new email":"email.received",
    "calendar event":"calendar.event.started","calendar event starts":"calendar.event.started",
}

def normalize_event_type(value:str)->str:
    raw=" ".join(str(value or "").strip().casefold().split())
    if raw in _ALIASES:return _ALIASES[raw]
    cleaned=re.sub(r"[^a-z0-9._-]+",".",raw).strip(".")
    if not cleaned:raise ValueError("External event type is required.")
    return cleaned[:160]

def publish_external_event(event_type:str,payload:dict[str,Any]|None=None,*,source:str="external",external_id:str|None=None)->dict[str,Any]:
    etype=normalize_event_type(event_type);key=f"external:{source}:{external_id}" if external_id else None
    return publish_event(etype,dict(payload or {}),source=str(source or "external")[:120],dedupe_key=key)

def webhook_security_state()->dict[str,Any]:
    token=bool(os.getenv("AGENTIE_AUTOMATION_WEBHOOK_TOKEN","").strip())
    return {"token_configured":token,"when_unconfigured":"loopback_only","native_sources":[{"event_type":k,"label":v} for k,v in sorted(_NATIVE.items())],"webhook_event_prefix":"Any normalized event type, e.g. email.received or crm.lead.created"}

def webhook_allowed(client_host:str|None,provided_token:str|None)->bool:
    expected=os.getenv("AGENTIE_AUTOMATION_WEBHOOK_TOKEN","").strip()
    if expected:
        import hmac
        return bool(provided_token) and hmac.compare_digest(str(provided_token),expected)
    host=str(client_host or "").strip().casefold()
    return host in {"127.0.0.1","::1","localhost","testclient"}

def event_alias(value:str)->str|None:
    low=" ".join(str(value or "").casefold().split())
    return _ALIASES.get(low)
