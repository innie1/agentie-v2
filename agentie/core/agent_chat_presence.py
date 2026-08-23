from __future__ import annotations

from typing import Any

from agentie.core import agent_threads
from agentie.core.agent_registry import get_agent, list_agents

_STATUS_RANK = {"working": 5, "queued": 4, "failed": 3, "done": 2, "idle": 1}


def _status_for_handoff(status: str) -> str:
    value = str(status or "").casefold()
    if value == "working": return "working"
    if value == "queued": return "queued"
    if value in {"failed", "cancelled"}: return "failed"
    if value in {"completed", "recovered"}: return "done"
    return "idle"


def _set_status(current: str, candidate: str) -> str:
    return candidate if _STATUS_RANK.get(candidate, 0) > _STATUS_RANK.get(current, 0) else current


def set_thread_owner(thread_id_or_name: str, agent_id_or_name: str | None) -> dict[str, Any]:
    items = agent_threads._load()
    key = str(thread_id_or_name or "").strip().casefold()
    thread = next((x for x in items if str(x.get("id") or "").casefold() == key or str(x.get("name") or "").casefold() == key), None)
    if not thread:
        raise ValueError("Agent chat was not found.")
    if not agent_id_or_name:
        thread["owner_agent_id"] = None
        thread["owner_agent_name"] = None
    else:
        agent = get_agent(str(agent_id_or_name))
        if not agent:
            raise ValueError("Agent was not found.")
        if agent["id"] not in thread.get("participant_ids", []):
            raise ValueError("Agent Chat owner must be a participant in that chat.")
        thread["owner_agent_id"] = agent["id"]
        thread["owner_agent_name"] = agent["name"]
    thread["updated_at"] = agent_threads._now()
    agent_threads._save(items)
    return agent_threads.get_thread(str(thread["id"])) or dict(thread)


def create_group_chat(name: str, participants: list[str], owner_agent_id: str | None = None) -> dict[str, Any]:
    resolved = []
    for raw in participants:
        agent = get_agent(str(raw))
        if not agent:
            raise ValueError(f"Agent {raw} was not found.")
        if agent["id"] not in [x["id"] for x in resolved]:
            resolved.append(agent)
    if len(resolved) < 2:
        raise ValueError("A group chat needs at least two existing agents.")
    thread = agent_threads.create_thread(name, [x["id"] for x in resolved])
    if owner_agent_id:
        thread = set_thread_owner(thread["id"], owner_agent_id)
    return thread


def _presence(thread_card: dict[str, Any]) -> list[dict[str, Any]]:
    participant_ids = list(thread_card.get("participant_ids") or [])
    participant_names = list(thread_card.get("participants") or [])
    rows = {str(aid): {"agent_id": str(aid), "agent_name": participant_names[i] if i < len(participant_names) else str(aid), "status": "idle", "outstanding_tasks": 0, "last_activity_at": None} for i, aid in enumerate(participant_ids)}
    seen_jobs: set[str] = set()
    for message in thread_card.get("messages") or []:
        sender_id = str(message.get("sender_id") or "")
        if sender_id in rows:
            rows[sender_id]["last_activity_at"] = message.get("at") or rows[sender_id]["last_activity_at"]
        meta = message.get("metadata") or {}
        job = message.get("job") or {}
        job_id = str(job.get("id") or meta.get("team_job_id") or "")
        if job_id:
            if job_id in seen_jobs:
                continue
            seen_jobs.add(job_id)
            if not job.get("handoffs"):
                job = agent_threads.get_team_job(job_id) or {}
        for handoff in job.get("handoffs") or []:
            handoff_agent_id = str(handoff.get("to_agent_id") or handoff.get("agent_id") or "")
            name = str(handoff.get("to_agent_name") or handoff.get("agent") or "")
            match_id = handoff_agent_id if handoff_agent_id in rows else next((aid for aid, row in rows.items() if row["agent_name"].casefold() == name.casefold()), None)
            if not match_id:
                continue
            status = _status_for_handoff(handoff.get("status"))
            rows[match_id]["status"] = _set_status(rows[match_id]["status"], status)
            if status in {"working", "queued"}:
                rows[match_id]["outstanding_tasks"] += 1
    return list(rows.values())


def connected_thread(thread: dict[str, Any]) -> dict[str, Any]:
    current = agent_threads.get_thread(str(thread.get("id"))) or thread
    owner_id = str(current.get("owner_agent_id") or "")
    if owner_id and owner_id not in {str(x) for x in current.get("participant_ids") or []}:
        current = set_thread_owner(str(current.get("id")), None)
    card = agent_threads.thread_card(current)
    latest = agent_threads.get_thread(str(current.get("id"))) or current
    card["owner_agent_id"] = latest.get("owner_agent_id")
    card["owner_agent_name"] = latest.get("owner_agent_name")
    card["presence"] = _presence(card)
    working = sum(1 for x in card["presence"] if x["status"] == "working")
    queued = sum(1 for x in card["presence"] if x["status"] == "queued")
    card["working_count"] = working
    card["queued_count"] = queued
    return card


def list_connected_threads() -> list[dict[str, Any]]:
    out = []
    for thread in agent_threads.list_threads():
        card = connected_thread(thread)
        out.append({
            "id": card.get("id"),
            "name": card.get("name"),
            "participant_ids": card.get("participant_ids") or [],
            "participants": card.get("participants") or [],
            "owner_agent_id": card.get("owner_agent_id"),
            "owner_agent_name": card.get("owner_agent_name"),
            "working_count": card.get("working_count", 0),
            "queued_count": card.get("queued_count", 0),
            "message_count": len(card.get("messages") or []),
            "updated_at": card.get("updated_at"),
        })
    return out


def available_agents() -> list[dict[str, Any]]:
    return [{"id": x["id"], "name": x["name"], "job": x.get("role"), "avatar_kind": x.get("avatar_kind"), "avatar_file": x.get("avatar_file")} for x in list_agents()]
