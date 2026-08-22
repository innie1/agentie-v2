from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from agentie.core.external_triggers import publish_external_event,webhook_allowed,webhook_security_state
from agentie.core.whatsapp_cloud import (
    connection_state,
    ingest_webhook,
    verify_webhook_challenge,
    verify_webhook_signature,
)

router = APIRouter()


def _whatsapp_body(message:dict)->str:
    kind=str(message.get("type") or "unknown")
    if kind=="text":return str((message.get("text") or {}).get("body") or "")
    if kind=="button":return str((message.get("button") or {}).get("text") or "")
    if kind=="interactive":
        value=message.get("interactive") or {};reply=value.get("button_reply") or value.get("list_reply") or {};return str(reply.get("title") or reply.get("id") or "")
    media=message.get(kind) if isinstance(message.get(kind),dict) else {};return str(media.get("caption") or f"[{kind} message]")

def _publish_whatsapp_events(payload:dict)->int:
    count=0
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value=change.get("value") or {}
            for message in value.get("messages") or []:
                mid=str(message.get("id") or "").strip();sender=str(message.get("from") or "").strip();kind=str(message.get("type") or "unknown")
                publish_external_event("whatsapp.message.received",{"message_id":mid,"from":sender,"type":kind,"body":_whatsapp_body(message),"timestamp":message.get("timestamp")},source="whatsapp_cloud",external_id=mid or None);count+=1
    return count


@router.get("/webhooks/whatsapp")
async def whatsapp_webhook_verify(request: Request):
    challenge = verify_webhook_challenge(
        request.query_params.get("hub.mode"),
        request.query_params.get("hub.verify_token"),
        request.query_params.get("hub.challenge"),
    )
    if challenge is None:
        raise HTTPException(403, "WhatsApp webhook verification failed.")
    return PlainTextResponse(challenge)


@router.post("/webhooks/whatsapp")
async def whatsapp_webhook_receive(request: Request):
    raw = await request.body();signature = request.headers.get("x-hub-signature-256")
    if not verify_webhook_signature(raw, signature):raise HTTPException(403, "WhatsApp webhook signature verification failed.")
    try:payload = await request.json()
    except Exception as exc:raise HTTPException(400, "WhatsApp webhook body must be valid JSON.") from exc
    if not isinstance(payload, dict):raise HTTPException(400, "WhatsApp webhook body must be a JSON object.")
    result = ingest_webhook(payload);automation_events=_publish_whatsapp_events(payload)
    return {"status": "ok", **result,"automation_events":automation_events}


@router.get("/whatsapp/connection-state")
async def whatsapp_connection_state():
    return connection_state()


@router.get("/automation/triggers/status")
async def automation_trigger_status():
    return webhook_security_state()


@router.post("/automation/webhooks/{event_type:path}")
async def automation_external_webhook(event_type:str,request:Request):
    """Secure ingress for real external services/plugins.

    If AGENTIE_AUTOMATION_WEBHOOK_TOKEN is configured, callers must send it in
    X-Agentie-Webhook-Token. Without a token this endpoint is deliberately
    loopback-only, so Agentie never exposes an unauthenticated LAN webhook.
    """
    if not webhook_allowed(request.client.host if request.client else None,request.headers.get("x-agentie-webhook-token")):raise HTTPException(403,"External automation webhook is not authorized.")
    try:payload=await request.json()
    except Exception as exc:raise HTTPException(400,"Automation webhook body must be valid JSON.") from exc
    if not isinstance(payload,dict):raise HTTPException(400,"Automation webhook body must be a JSON object.")
    external_id=str(payload.get("id") or payload.get("event_id") or request.headers.get("x-event-id") or "").strip() or None
    event=publish_external_event(event_type,payload,source="automation_webhook",external_id=external_id)
    return {"accepted":True,"event":event}
