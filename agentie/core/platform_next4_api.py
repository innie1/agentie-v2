from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from agentie.core import agent_threads
from agentie.core.agent_chat_presence import available_agents, connected_thread, create_group_chat, list_connected_threads, set_thread_owner
from agentie.core.google_workspace_events import add_drive_watch, bridge_status, poll_enabled_sources, remove_drive_watch, start_google_workspace_event_bridge, update_settings
from agentie.core.group_chat_policy import install_group_chat_policy
from agentie.core.model_routing import routing_status, set_mode
from agentie.core.skill_marketplace import assign_marketplace_item, install_marketplace_item, search_marketplace, share_installed_skill

router = APIRouter()
install_group_chat_policy()


def _frontend_script(name: str) -> Response:
    path = Path(__file__).resolve().parents[2] / "frontend" / name
    return Response(path.read_text(encoding="utf-8"), media_type="application/javascript", headers={"Cache-Control": "no-store"})


def _frontend_bundle(*names: str) -> Response:
    frontend = Path(__file__).resolve().parents[2] / "frontend"
    content = "\n".join((frontend / name).read_text(encoding="utf-8") for name in names)
    return Response(content, media_type="application/javascript", headers={"Cache-Control": "no-store"})


async def _json(request: Request) -> dict[str, Any]:
    try:
        value = await request.json()
    except Exception as exc:
        raise HTTPException(400, "Request body must be valid JSON.") from exc
    if not isinstance(value, dict):
        raise HTTPException(400, "Request body must be a JSON object.")
    return value


def _default_group_job_metadata(thread: dict[str, Any], message: str) -> dict[str, Any] | None:
    """Address an unmentioned user message to every participant in the group.

    Explicit @mentions keep the existing targeted behavior in agent_threads.
    This only fills the natural group-chat case where the user simply types a
    message into a group and reasonably expects the group members to answer.
    """
    if agent_threads._mentioned_agents(thread, message):
        return None
    agents = []
    for agent_id in thread.get("participant_ids") or []:
        agent = agent_threads.get_agent(str(agent_id))
        if agent and all(existing["id"] != agent["id"] for existing in agents):
            agents.append(agent)
    if not agents:
        return None
    task = agent_threads._task_without_mentions(message, agents)
    mode = agent_threads._interaction_mode(task)
    job = agent_threads.create_team_job(task, agents, requested_by="user", interaction_mode=mode)
    agent_threads.start_team_job(job["id"])
    return {
        "team_job_id": job["id"],
        "to_agent_ids": [agent["id"] for agent in agents],
        "mentions": [agent["name"] for agent in agents],
        "materialize_replies": True,
        "interaction_mode": mode,
        "source": "group_chat_default_all",
    }


@router.on_event("startup")
async def _start_google_event_bridge() -> None:
    start_google_workspace_event_bridge()


@router.get("/platform-automation.js")
async def platform_automation_js():
    return _frontend_script("platform_automation.js")


@router.get("/platform-permission-guard.js")
async def platform_permission_guard_js():
    return _frontend_script("platform_permission_guard.js")


@router.get("/platform-model-router.js")
async def platform_model_router_js():
    return _frontend_script("model_router.js")


@router.get("/platform-chat-focus-guard.js")
async def platform_chat_focus_guard_js():
    return _frontend_script("platform_chat_focus_guard.js")


@router.get("/platform-group-chat-markdown.js")
async def platform_group_chat_markdown_js():
    return _frontend_script("group_chat_markdown.js")


@router.get("/platform-group-chat-offline-cache.js")
async def platform_group_chat_offline_cache_js():
    return _frontend_script("group_chat_offline_cache.js")


@router.get("/platform-navigation-connect.js")
async def platform_navigation_connect_js():
    return _frontend_script("navigation_connect.js")


@router.get("/platform-group-instant-open.js")
async def platform_group_instant_open_js():
    return _frontend_script("group_chat_instant_open.js")


@router.get("/platform-create-menu.js")
async def platform_create_menu_js():
    return _frontend_script("create_menu.js")


@router.get("/platform-create-menu-loader.js")
async def platform_create_menu_loader_js():
    return _frontend_script("create_menu_loader.js")


@router.get("/platform-next4.js")
async def platform_next4_js():
    # Keep startup light: only the tiny create-menu loader is part of the main
    # platform bundle. The full creation conversation is fetched after + is
    # clicked. Group navigation remains the owner of visible group-chat state.
    return _frontend_bundle("platform_next4.js", "platform_chat_focus_guard.js", "group_chat_markdown.js", "model_router.js", "group_chat_offline_cache.js", "navigation_connect.js", "group_chat_instant_open.js", "create_menu_loader.js")


@router.get("/platform/model-routing/status")
async def platform_model_routing_status(verify: bool = True):
    return routing_status(verify_local=verify)


@router.post("/platform/model-routing/mode")
async def platform_model_routing_mode(request: Request):
    data = await _json(request)
    try:
        return set_mode(str(data.get("mode") or ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


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
    metadata = None
    if target:
        agent = next((x for x in available_agents() if str(x["id"]) == target), None)
        if not agent or target not in thread.get("participant_ids", []):
            raise HTTPException(400, "Target agent is not a participant in this chat.")
        message = f"@{agent['name']} {message}"
    else:
        metadata = _default_group_job_metadata(thread, message)
    agent_threads.post_message(thread["id"], "user", None, "User", message, metadata)
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


# Some Windows/FastAPI environments used by Agentie have been observed to
# return from include_router() without copying this populated router's APIRoutes.
# Keep the normal framework path first, then narrowly repair only this exact
# platform router if none/some of its routes were copied. This runs before
# main.py creates the FastAPI app because this module is imported first.
_original_include_router = APIRouter.include_router


def _route_key(item: Any) -> tuple[str | None, tuple[str, ...]]:
    return (getattr(item, "path", None), tuple(sorted(getattr(item, "methods", None) or ())))


def _include_router_with_platform_fallback(self: APIRouter, other: APIRouter, *args: Any, **kwargs: Any):
    result = _original_include_router(self, other, *args, **kwargs)
    if other is router:
        existing = {_route_key(item) for item in self.routes}
        for item in other.routes:
            key = _route_key(item)
            if key not in existing:
                self.routes.append(item)
                existing.add(key)
        for handler in getattr(other, "on_startup", ()):
            if handler not in self.on_startup:
                self.on_startup.append(handler)
        for handler in getattr(other, "on_shutdown", ()):
            if handler not in self.on_shutdown:
                self.on_shutdown.append(handler)
    return result


if not getattr(APIRouter.include_router, "__agentie_platform_fallback__", False):
    _include_router_with_platform_fallback.__agentie_platform_fallback__ = True
    APIRouter.include_router = _include_router_with_platform_fallback
