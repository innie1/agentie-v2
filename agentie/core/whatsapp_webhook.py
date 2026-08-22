from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response

from agentie.core import agent_threads
from agentie.core.agent_chat_presence import available_agents, connected_thread, create_group_chat, list_connected_threads, set_thread_owner
from agentie.core.external_triggers import publish_external_event, webhook_allowed, webhook_security_state
from agentie.core.google_workspace_events import add_drive_watch, bridge_status, poll_enabled_sources, remove_drive_watch, start_google_workspace_event_bridge, update_settings
from agentie.core.skill_marketplace import assign_marketplace_item, install_marketplace_item, search_marketplace, share_installed_skill
from agentie.core.whatsapp_cloud import connection_state, ingest_webhook, verify_webhook_challenge, verify_webhook_signature

# main.py includes this router directly. Keep every connected platform route that
# must exist at runtime on this router itself; do not depend on nested-router
# propagation or duplicate /platform.js ownership.
router = APIRouter()


def _frontend_script(name: str) -> Response:
    path = Path(__file__).resolve().parents[2] / "frontend" / name
    return Response(path.read_text(encoding="utf-8"), media_type="application/javascript", headers={"Cache-Control": "no-store"})


async def _json(request: Request) -> dict[str, Any]:
    try:
        value = await request.json()
    except Exception as exc:
        raise HTTPException(400, "Request body must be valid JSON.") from exc
    if not isinstance(value, dict):
        raise HTTPException(400, "Request body must be a JSON object.")
    return value


# Compatibility helper used by regression coverage. It deliberately is NOT a
# route. main.py is the single owner of /platform.js.
async def enhanced_platform_js() -> Response:
    frontend = Path(__file__).resolve().parents[2] / "frontend"
    names = ("platform.js", "platform_automation.js", "platform_permission_guard.js", "platform_next4.js")
    content = "\n".join((frontend / name).read_text(encoding="utf-8") for name in names)
    return Response(content, media_type="application/javascript", headers={"Cache-Control": "no-store"})


@router.on_event("startup")
async def _start_google_event_bridge() -> None:
    start_google_workspace_event_bridge()


@router.get("/platform-automation.js")
async def platform_automation_js():
    return _frontend_script("platform_automation.js")


@router.get("/platform-permission-guard.js")
async def platform_permission_guard_js():
    return _frontend_script("platform_permission_guard.js")


@router.get("/platform-next4.js")
async def platform_next4_js():
    return _frontend_script("platform_next4.js")


@router.get("/platform/agents")
async def platform_agents():
    return {"items": available_agents()}


@router.get("/platform/agent-chats")
async def platform_agent_chats():
    return {"items": list_connected_threads()}


@router.post("/platform/agent-chats")
async def platform_agent_chats_create(request: Request):
    data = await _json(request)
    participants = data.get("participants") or []
    if not isinstance(participants, list):
        raise HTTPException(400, "participants must be a list of agent IDs or names.")
    try:
        thread = create_group_chat(
            str(data.get("name") or "").strip(),
            [str(x) for x in participants],
            str(data.get("owner_agent_id") or "") or None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return connected_thread(thread)


@router.get("/platform/agent-chats/{thread_id}")
async def platform_agent_chat_get(thread_id: str):
    thread = agent_threads.get_thread(thread_id)
    if not thread:
        raise HTTPException(404, "Agent chat was not found.")
    return connected_thread(thread)


@router.post("/platform/agent-chats/{thread_id}/owner")
async def platform_agent_chat_owner(thread_id: str, request: Request):
    data = await _json(request)
    try:
        thread = set_thread_owner(thread_id, str(data.get("agent_id") or "") or None)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return connected_thread(thread)


@router.post("/platform/agent-chats/{thread_id}/messages")
async def platform_agent_chat_message(thread_id: str, request: Request):
    thread = agent_threads.get_thread(thread_id)
    if not thread:
        raise HTTPException(404, "Agent chat was not found.")
    data = await _json(request)
    message = str(data.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "Message is required.")
    target = str(data.get("target_agent_id") or "").strip()
    if target:
        agent = next((x for x in available_agents() if str(x["id"]) == target), None)
        if not agent or target not in thread.get("participant_ids", []):
            raise HTTPException(400, "Target agent is not a participant in this chat.")
        message = f"@{agent['name']} {message}"
    agent_threads.post_message(thread["id"], "user", None, "User", message)
    return connected_thread(agent_threads.get_thread(thread["id"]) or thread)


@router.post("/platform/agent-chats/{thread_id}/messages/{message_id}/reply")
async def platform_agent_chat_reply(thread_id: str, message_id: str, request: Request):
    data = await _json(request)
    message = str(data.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "Reply message is required.")
    try:
        agent_threads.reply_to_message(thread_id, message_id, message)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    thread = agent_threads.get_thread(thread_id)
    if not thread:
        raise HTTPException(404, "Agent chat was not found.")
    return connected_thread(thread)


@router.post("/platform/agent-chats/{thread_id}/messages/{message_id}/reaction")
async def platform_agent_chat_reaction(thread_id: str, message_id: str, request: Request):
    data = await _json(request)
    try:
        agent_threads.react_to_message(thread_id, message_id, str(data.get("reaction") or ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    thread = agent_threads.get_thread(thread_id)
    if not thread:
        raise HTTPException(404, "Agent chat was not found.")
    return connected_thread(thread)


@router.get("/platform/google-events/status")
async def platform_google_events_status(verify: bool = False):
    return await bridge_status(verify_connection=verify)


@router.post("/platform/google-events/settings")
async def platform_google_events_settings(request: Request):
    data = await _json(request)
    state = update_settings(
        gmail_enabled=data.get("gmail_enabled") if "gmail_enabled" in data else None,
        calendar_enabled=data.get("calendar_enabled") if "calendar_enabled" in data else None,
    )
    return {**state, "status": await bridge_status(verify_connection=False)}


@router.post("/platform/google-events/drive-watch")
async def platform_google_drive_watch(request: Request):
    data = await _json(request)
    try:
        watch = add_drive_watch(
            str(data.get("item_id") or ""),
            kind=str(data.get("kind") or "file"),
            label=str(data.get("label") or ""),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"watch": watch, "status": await bridge_status(verify_connection=False)}


@router.delete("/platform/google-events/drive-watch/{watch_id}")
async def platform_google_drive_watch_delete(watch_id: str):
    if not remove_drive_watch(watch_id):
        raise HTTPException(404, "Drive watch was not found.")
    return {"removed": True, "watch_id": watch_id}


@router.post("/platform/google-events/poll-now")
async def platform_google_events_poll_now():
    return await poll_enabled_sources()


@router.get("/platform/skills/marketplace")
async def platform_skill_marketplace(q: str = "", agent_id: str | None = None):
    return search_marketplace(q, agent_id=agent_id)


@router.post("/platform/skills/marketplace/{catalog_id:path}/install")
async def platform_skill_marketplace_install(catalog_id: str):
    try:
        item = install_marketplace_item(catalog_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    from agentie.core.workflow_skills import skill_card
    return skill_card(item)


@router.post("/platform/skills/marketplace/{catalog_id:path}/assign/{agent_id}")
async def platform_skill_marketplace_assign(catalog_id: str, agent_id: str):
    try:
        return assign_marketplace_item(catalog_id, agent_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/platform/skills/{skill_id}/share")
async def platform_skill_share(skill_id: str):
    try:
        return share_installed_skill(skill_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _whatsapp_body(message: dict) -> str:
    kind = str(message.get("type") or "unknown")
    if kind == "text":
        return str((message.get("text") or {}).get("body") or "")
    if kind == "button":
        return str((message.get("button") or {}).get("text") or "")
    if kind == "interactive":
        value = message.get("interactive") or {}
        reply = value.get("button_reply") or value.get("list_reply") or {}
        return str(reply.get("title") or reply.get("id") or "")
    media = message.get(kind) if isinstance(message.get(kind), dict) else {}
    return str(media.get("caption") or f"[{kind} message]")


def _publish_whatsapp_events(payload: dict) -> int:
    count = 0
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            for message in value.get("messages") or []:
                mid = str(message.get("id") or "").strip()
                sender = str(message.get("from") or "").strip()
                kind = str(message.get("type") or "unknown")
                publish_external_event(
                    "whatsapp.message.received",
                    {"message_id": mid, "from": sender, "type": kind, "body": _whatsapp_body(message), "timestamp": message.get("timestamp")},
                    source="whatsapp_cloud",
                    external_id=mid or None,
                )
                count += 1
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
    automation_events = _publish_whatsapp_events(payload)
    return {"status": "ok", **result, "automation_events": automation_events}


@router.get("/whatsapp/connection-state")
async def whatsapp_connection_state():
    return connection_state()


@router.get("/automation/triggers/status")
async def automation_trigger_status():
    return webhook_security_state()


@router.post("/automation/webhooks/{event_type:path}")
async def automation_external_webhook(event_type: str, request: Request):
    if not webhook_allowed(request.client.host if request.client else None, request.headers.get("x-agentie-webhook-token")):
        raise HTTPException(403, "External automation webhook is not authorized.")
    payload = await _json(request)
    external_id = str(payload.get("id") or payload.get("event_id") or request.headers.get("x-event-id") or "").strip() or None
    event = publish_external_event(event_type, payload, source="automation_webhook", external_id=external_id)
    return {"accepted": True, "event": event}


@router.get("/skill-library")
async def skill_library_get():
    from agentie.core.skill_library import list_library
    return list_library()


@router.post("/skill-library/templates/{template_id}/install")
async def skill_template_install(template_id: str):
    from agentie.core.skill_library import install_template
    from agentie.core.workflow_skills import skill_card
    try:
        return skill_card(install_template(template_id))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/skill-library/{skill_id}/duplicate")
async def skill_duplicate(skill_id: str, request: Request):
    from agentie.core.skill_library import duplicate_skill
    from agentie.core.workflow_skills import skill_card
    data = await _json(request)
    try:
        return skill_card(duplicate_skill(skill_id, str(data.get("name") or "")))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/skill-library/{skill_id}/assign/{agent_id}")
async def skill_assign(skill_id: str, agent_id: str):
    from agentie.core.skill_library import assign_skill
    try:
        return assign_skill(skill_id, agent_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/skill-library/{skill_id}/status/{status}")
async def skill_status(skill_id: str, status: str):
    from agentie.core.workflow_skills import set_workflow_skill_status, skill_card
    try:
        return skill_card(set_workflow_skill_status(skill_id, status))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# Legacy richer-thread endpoints retained for compatibility with existing UI/tests.
@router.post("/agent-threads/{thread_id}/messages/{message_id}/reply")
async def agent_chat_reply(thread_id: str, message_id: str, request: Request):
    data = await _json(request)
    text = str(data.get("message") or "").strip()
    if not text:
        raise HTTPException(400, "Reply message is required.")
    try:
        agent_threads.reply_to_message(thread_id, message_id, text)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    thread = agent_threads.get_thread(thread_id)
    if not thread:
        raise HTTPException(404, "Agent chat was not found.")
    return agent_threads.thread_card(thread)


@router.post("/agent-threads/{thread_id}/messages/{message_id}/reaction")
async def agent_chat_reaction(thread_id: str, message_id: str, request: Request):
    data = await _json(request)
    try:
        agent_threads.react_to_message(thread_id, message_id, str(data.get("reaction") or ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    thread = agent_threads.get_thread(thread_id)
    if not thread:
        raise HTTPException(404, "Agent chat was not found.")
    return agent_threads.thread_card(thread)
