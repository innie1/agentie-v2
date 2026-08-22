from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse,Response

from agentie.core.external_triggers import publish_external_event,webhook_allowed,webhook_security_state
from agentie.core.whatsapp_cloud import connection_state,ingest_webhook,verify_webhook_challenge,verify_webhook_signature

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
async def _json(request:Request)->dict:
    try:value=await request.json()
    except Exception as exc:raise HTTPException(400,"Request body must be valid JSON.") from exc
    if not isinstance(value,dict):raise HTTPException(400,"Request body must be a JSON object.")
    return value

# main.py already loads /platform.js. This route is included before main's
# compatibility route, so the same browser request now receives the stable base
# platform UI plus the additive automation/library/chat layer. No second app shell.
@router.get("/platform.js")
async def enhanced_platform_js():
    frontend=Path(__file__).resolve().parents[2]/"frontend";base=(frontend/"platform.js").read_text(encoding="utf-8");extra=(frontend/"platform_automation.js").read_text(encoding="utf-8")
    return Response(base+"\n"+extra,media_type="application/javascript",headers={"Cache-Control":"no-store"})

@router.get("/webhooks/whatsapp")
async def whatsapp_webhook_verify(request: Request):
    challenge = verify_webhook_challenge(request.query_params.get("hub.mode"),request.query_params.get("hub.verify_token"),request.query_params.get("hub.challenge"))
    if challenge is None:raise HTTPException(403, "WhatsApp webhook verification failed.")
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
async def whatsapp_connection_state():return connection_state()

@router.get("/automation/triggers/status")
async def automation_trigger_status():return webhook_security_state()
@router.post("/automation/webhooks/{event_type:path}")
async def automation_external_webhook(event_type:str,request:Request):
    if not webhook_allowed(request.client.host if request.client else None,request.headers.get("x-agentie-webhook-token")):raise HTTPException(403,"External automation webhook is not authorized.")
    payload=await _json(request);external_id=str(payload.get("id") or payload.get("event_id") or request.headers.get("x-event-id") or "").strip() or None
    event=publish_external_event(event_type,payload,source="automation_webhook",external_id=external_id);return {"accepted":True,"event":event}

@router.get("/skill-library")
async def skill_library_get():
    from agentie.core.skill_library import list_library
    return list_library()
@router.post("/skill-library/templates/{template_id}/install")
async def skill_template_install(template_id:str):
    from agentie.core.skill_library import install_template
    from agentie.core.workflow_skills import skill_card
    try:return skill_card(install_template(template_id))
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
@router.post("/skill-library/{skill_id}/duplicate")
async def skill_duplicate(skill_id:str,request:Request):
    from agentie.core.skill_library import duplicate_skill
    from agentie.core.workflow_skills import skill_card
    data=await _json(request)
    try:return skill_card(duplicate_skill(skill_id,str(data.get("name") or "")))
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
@router.post("/skill-library/{skill_id}/assign/{agent_id}")
async def skill_assign(skill_id:str,agent_id:str):
    from agentie.core.skill_library import assign_skill
    try:return assign_skill(skill_id,agent_id)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
@router.post("/skill-library/{skill_id}/status/{status}")
async def skill_status(skill_id:str,status:str):
    from agentie.core.workflow_skills import set_workflow_skill_status,skill_card
    try:return skill_card(set_workflow_skill_status(skill_id,status))
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc

@router.post("/agent-threads/{thread_id}/messages/{message_id}/reply")
async def agent_chat_reply(thread_id:str,message_id:str,request:Request):
    from agentie.core.agent_threads import get_thread,reply_to_message,thread_card
    data=await _json(request);text=str(data.get("message") or "").strip()
    if not text:raise HTTPException(400,"Reply message is required.")
    try:reply_to_message(thread_id,message_id,text)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    thread=get_thread(thread_id)
    if not thread:raise HTTPException(404,"Agent chat was not found.")
    return thread_card(thread)
@router.post("/agent-threads/{thread_id}/messages/{message_id}/reaction")
async def agent_chat_reaction(thread_id:str,message_id:str,request:Request):
    from agentie.core.agent_threads import get_thread,react_to_message,thread_card
    data=await _json(request);reaction=str(data.get("reaction") or "")
    try:react_to_message(thread_id,message_id,reaction)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    thread=get_thread(thread_id)
    if not thread:raise HTTPException(404,"Agent chat was not found.")
    return thread_card(thread)
