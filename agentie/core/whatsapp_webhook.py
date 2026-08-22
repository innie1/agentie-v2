from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from agentie.core.whatsapp_cloud import (
    connection_state,
    ingest_webhook,
    verify_webhook_challenge,
    verify_webhook_signature,
)

router = APIRouter()


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
    raw = await request.body()
    signature = request.headers.get("x-hub-signature-256")
    if not verify_webhook_signature(raw, signature):
        raise HTTPException(403, "WhatsApp webhook signature verification failed.")
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(400, "WhatsApp webhook body must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, "WhatsApp webhook body must be a JSON object.")
    result = ingest_webhook(payload)
    return {"status": "ok", **result}


@router.get("/whatsapp/connection-state")
async def whatsapp_connection_state():
    """Public-safe setup state. Never returns tokens or app secrets."""
    return connection_state()
