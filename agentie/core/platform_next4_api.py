from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from agentie.core import agent_threads
from agentie.core.agent_chat_presence import available_agents, connected_thread, create_group_chat, list_connected_threads, set_thread_owner
from agentie.core.google_workspace_events import add_drive_watch, bridge_status, poll_enabled_sources, remove_drive_watch, start_google_workspace_event_bridge, update_settings
from agentie.core.skill_marketplace import assign_marketplace_item, install_marketplace_item, search_marketplace, share_installed_skill

router = APIRouter()


async def _json(request: Request) -> dict[str, Any]:
    try:
        value = await request.json()
    except Exception as exc:
        raise HTTPException(400, "Request body must be valid JSON.") from exc
    if not isinstance(value, dict):
        raise HTTPException(400, "Request body must be a JSON object.")
    return value


@router.on_event("startup")
async def _start_google_event_bridge() -> None:
    start_google_workspace_event_bridge()


@router.get("/platform-next4.js")
async def platform_next4_js():
    path = Path(__file__).resolve().parents[2] / "frontend" / "platform_next4.js"
    return Response(path.read_text(encoding="utf-8"), media_type="application/javascript", headers={"Cache-Control": "no-store"})


@router.get("/platform/agents")
async def platform_agents():
    return {"items": available_agents()}


@router.get("/platform/agent-chats")
async def platform_agent_chats():
    return {"items": list_connected_threads()}


@router.post("/platform/agent-chats")
async def platform_agent_chats_create(request: Request):
    data = await _json(request)
    name = str(data.get("name") or "").strip()
    participants = data.get("participants") or []
    if not isinstance(participants, list):
        raise HTTPException(400, "participants must be a list of agent IDs or names.")
    try:
        thread = create_group_chat(name, [str(x) for x in participants], str(data.get("owner_agent_id") or "") or None)
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
    state = update_settings(gmail_enabled=data.get("gmail_enabled") if "gmail_enabled" in data else None, calendar_enabled=data.get("calendar_enabled") if "calendar_enabled" in data else None)
    return {**state, "status": await bridge_status(verify_connection=False)}


@router.post("/platform/google-events/drive-watch")
async def platform_google_drive_watch(request: Request):
    data = await _json(request)
    try:
        watch = add_drive_watch(str(data.get("item_id") or ""), kind=str(data.get("kind") or "file"), label=str(data.get("label") or ""))
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
