from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agentie.core import team_orchestrator as team
from agentie.core.agent_registry import get_agent

_ACTIVE_STATUSES = {"queued", "working"}
_TERMINAL_JOB_STATUSES = {"completed", "failed", "partial", "cancelled"}


@dataclass(frozen=True)
class StaleHandoffConfig:
    """How long a handoff can sit untouched before it gets nudged/escalated.

    Every threshold has an env override so this can be tuned per deployment
    (e.g. a WhatsApp-facing Agentie for a small business vs. a dev sandbox)
    without a code change.
    """
    nudge_after_seconds: int = int(os.getenv("AGENTIE_STALL_NUDGE_SECONDS", "1800"))  # 30 min
    escalate_after_nudges: int = int(os.getenv("AGENTIE_STALL_ESCALATE_AFTER_NUDGES", "2"))


def _default_config() -> StaleHandoffConfig:
    return StaleHandoffConfig()


def _parse_at(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _reference_time(job: dict[str, Any], handoff: dict[str, Any]) -> datetime | None:
    """The last time we know this handoff actually moved."""
    for key in ("status_checked_at", "started_at"):
        parsed = _parse_at(handoff.get(key))
        if parsed:
            return parsed
    return _parse_at(job.get("created_at"))


def _publish(event_type: str, payload: dict[str, Any], dedupe_key: str | None = None) -> None:
    try:
        from agentie.core.automation_events import publish_event
        publish_event(event_type, payload, source="stale_handoff_monitor", dedupe_key=dedupe_key)
    except Exception:
        pass


def _nudge_note(handoff: dict[str, Any], nudge_number: int) -> str:
    task = str(handoff.get("task") or "the assigned work")
    return f"Checking in — still {handoff.get('status') or 'in progress'} on: {task}. (auto follow-up #{nudge_number})"


def _apply_nudge(job_id: str, handoff_id: str, note: str, now: datetime) -> None:
    def mutate(job: dict[str, Any]) -> None:
        for h in job.get("handoffs", []):
            if h.get("id") != handoff_id:
                continue
            h["stall_nudge_count"] = int(h.get("stall_nudge_count") or 0) + 1
            h["progress_summary"] = note
            h["status_checked_at"] = now.isoformat(timespec="seconds")
    team._mutate(job_id, mutate)


def _apply_escalation_flag(job_id: str, handoff_id: str, escalation_job_id: str | None) -> None:
    def mutate(job: dict[str, Any]) -> None:
        for h in job.get("handoffs", []):
            if h.get("id") != handoff_id:
                continue
            h["stall_escalated"] = True
            h["stall_escalation_job_id"] = escalation_job_id
    team._mutate(job_id, mutate)


def _escalate(job: dict[str, Any], handoff: dict[str, Any]) -> str | None:
    """Hand a stuck handoff back to its owning manager. Returns the new job id, or None.

    Only fires when the stalled job was created by a real, delegate-capable
    agent (the manager-autopilot / agent-to-agent path). User-initiated jobs
    never trigger an automatic model call here; they only get an event so an
    event-driven routine or the UI layer can decide what to do.
    """
    requested_by = str(job.get("requested_by") or "")
    manager = get_agent(requested_by) if requested_by else None
    if not manager or not bool((manager.get("permissions") or {}).get("delegate")):
        _publish(
            "team_job.handoff_needs_attention",
            {"team_job_id": job.get("id"), "handoff_id": handoff.get("id"), "agent_name": handoff.get("to_agent_name"), "task": handoff.get("task")},
            dedupe_key=f"stall-attention:{job.get('id')}:{handoff.get('id')}",
        )
        return None
    if str(manager.get("id")) == str(handoff.get("to_agent_id")):
        return None  # a manager can't escalate a handoff to itself
    summary = f"Handoff to {handoff.get('to_agent_name')} has been stalled ({handoff.get('progress_summary') or 'no progress reported'}). Original task: {handoff.get('task')}. Check in, unblock, or reassign it."
    escalation = team.create_team_job(summary, [manager], requested_by=str(manager.get("id")), project_id=job.get("project_id"))
    team.start_team_job(escalation["id"])
    _publish(
        "team_job.handoff_escalated",
        {"team_job_id": job.get("id"), "handoff_id": handoff.get("id"), "escalation_job_id": escalation["id"], "manager_id": manager.get("id"), "manager_name": manager.get("name")},
        dedupe_key=f"stall-escalate:{job.get('id')}:{handoff.get('id')}",
    )
    return str(escalation["id"])


def scan_and_nudge(now: datetime | None = None, config: StaleHandoffConfig | None = None) -> list[dict[str, Any]]:
    """One pass over all active team jobs. Call this on a schedule (see routine_worker).

    Fully local and safe to call often: reading/writing team_jobs.json and
    publishing local events only. Returns the list of actions taken, for
    logging/tests.
    """
    now = now or datetime.now().astimezone()
    cfg = config or _default_config()
    actions: list[dict[str, Any]] = []
    for job in team.list_team_jobs(200):
        if str(job.get("status") or "") in _TERMINAL_JOB_STATUSES:
            continue
        for handoff in job.get("handoffs", []):
            if str(handoff.get("status") or "") not in _ACTIVE_STATUSES:
                continue
            if handoff.get("stall_escalated"):
                continue
            reference = _reference_time(job, handoff)
            if reference is None:
                continue
            elapsed = (now - reference).total_seconds()
            nudge_count = int(handoff.get("stall_nudge_count") or 0)
            due_at = cfg.nudge_after_seconds * (nudge_count + 1)
            if elapsed < due_at:
                continue
            if nudge_count < cfg.escalate_after_nudges:
                note = _nudge_note(handoff, nudge_count + 1)
                _apply_nudge(job["id"], handoff["id"], note, now)
                _publish(
                    "team_job.handoff_stalled",
                    {"team_job_id": job["id"], "handoff_id": handoff["id"], "agent_name": handoff.get("to_agent_name"), "nudge_count": nudge_count + 1, "task": handoff.get("task")},
                    dedupe_key=f"stall-nudge:{job['id']}:{handoff['id']}:{nudge_count + 1}",
                )
                actions.append({"action": "nudged", "team_job_id": job["id"], "handoff_id": handoff["id"], "nudge_count": nudge_count + 1})
            else:
                escalation_job_id = _escalate(job, handoff)
                _apply_escalation_flag(job["id"], handoff["id"], escalation_job_id)
                actions.append({"action": "escalated" if escalation_job_id else "needs_attention", "team_job_id": job["id"], "handoff_id": handoff["id"], "escalation_job_id": escalation_job_id})
    return actions
