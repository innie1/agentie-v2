from __future__ import annotations

import re
import threading
import time
from typing import Any

from agentie.core.agent_registry import get_agent, list_agents
from agentie.core.memory_store import set_context
from agentie.core.team_orchestrator import create_team_job, get_team_job, start_team_job, team_job_card

_CONTROLLERS: dict[str, threading.Thread] = {}
_CONTROLLER_LOCK = threading.Lock()

_PHASE_TERMS = {
    "research": {"research", "researcher", "critic", "analyst", "market", "competitor", "evidence", "investigate"},
    "coding": {"cto", "coder", "coding", "developer", "engineer", "software", "technical", "github reviewer", "github"},
    "writing": {"writer", "content writer", "content", "copywriter", "copy", "script", "editor"},
    "verification": {"verifier", "verification", "qa", "quality", "reviewer", "critic", "fact checker", "tester"},
}


def _words(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _active_manager(session_id: str | None) -> dict[str, Any] | None:
    m = re.match(r"^agent:(agt_[a-z0-9]+):", str(session_id or ""), re.I)
    if not m:
        return None
    agent = get_agent(m.group(1))
    if not agent:
        return None
    role = f"{agent.get('role','')} {agent.get('purpose','')}".casefold()
    permissions = agent.get("permissions") or {}
    if agent.get("base") == "manager" or bool(permissions.get("delegate")) or re.search(r"\b(ceo|manager|chief of staff|coordinator)\b", role):
        return agent
    return None


def _agent_score(agent: dict[str, Any], phase: str, goal: str) -> int:
    text = f"{agent.get('name','')} {agent.get('role','')} {agent.get('purpose','')} {agent.get('base','')}".casefold()
    words = _words(text)
    score = 0
    for term in _PHASE_TERMS.get(phase, set()):
        score += 4 if " " in term and term in text else 2 if term in words else 0
    goal_words = _words(goal)
    score += min(4, len(goal_words & words))
    if phase == "verification" and "verifier" in words:
        score += 8
    if phase == "coding" and ("cto" in words or agent.get("base") == "coding"):
        score += 6
    if phase == "research" and agent.get("base") == "research":
        score += 5
    return score


def _best_agent(phase: str, goal: str, manager_id: str, used: set[str]) -> dict[str, Any] | None:
    scored = []
    for agent in list_agents():
        if str(agent.get("id")) == str(manager_id):
            continue
        score = _agent_score(agent, phase, goal)
        if score <= 0:
            continue
        if agent.get("id") in used:
            score -= 3
        scored.append((score, agent))
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], str(item[1].get("name", "")).casefold()))
    return scored[0][1]


def _phase_names(goal: str) -> list[str]:
    low = " ".join(str(goal or "").casefold().split())
    # Existing research->artifact jobs already have a purpose-built local job path.
    if re.search(r"\b(pdf|docx|docs? file|word file|xlsx|spreadsheet|pptx|powerpoint)\b", low):
        return []
    phases: list[str] = []
    software = bool(re.search(r"\b(app|application|software|website|web app|api|backend|frontend|database|code|implement|build)\b", low))
    content = bool(re.search(r"\b(content|post|campaign|article|blog|script|copy|newsletter|launch message)\b", low))
    research = bool(re.search(r"\b(research|compare|competitor|market|evidence|latest|investigate|find out)\b", low))
    verify = bool(re.search(r"\b(verify|review|check|test|launch|production|ready|readiness)\b", low))
    strategic = bool(re.search(r"\b(product|business|strategy|launch|project|roadmap|plan)\b", low))
    if research or software or content or strategic:
        phases.append("research")
    if software:
        phases.append("coding")
    elif content:
        phases.append("writing")
    if verify or software or content:
        phases.append("verification")
    return list(dict.fromkeys(phases))


def _advice_only(goal: str) -> bool:
    low = " ".join(str(goal or "").casefold().split())
    advice = bool(re.search(r"\b(?:what do you think|do you think|your opinion|should we|should i|would you recommend|do you recommend|which (?:one )?is better|which should we|which should i|best option|good idea|bad idea|worth it|what should we prioritize|what should i prioritize|what would you do)\b", low))
    if not advice:
        return False
    explicit_proceed = bool(re.search(r"\b(?:go ahead|do it|proceed|start (?:it|now|the work)|execute (?:it|that)|make it happen|carry it out)\b", low))
    return not explicit_proceed


def _autopilot_worthy(goal: str) -> bool:
    low = " ".join(str(goal or "").casefold().split())
    if _advice_only(low):
        return False
    if re.search(r"\b(pdf|docx|docs? file|word file|xlsx|spreadsheet|pptx|powerpoint)\b", low):
        return False
    # Building/implementing a software product is inherently multi-stage.
    if re.search(r"\b(build|implement|develop|create)\b[^.]{0,90}\b(app|application|software|website|web app|api|backend|frontend|database)\b", low):
        return True
    # Explicit end-to-end or campaign/strategy work is intentionally orchestrated.
    if re.search(r"\b(end[- ]to[- ]end|from research to|full workflow|complete workflow|launch campaign|marketing campaign|business strategy|product strategy)\b", low):
        return True
    action_hits = sum(bool(re.search(pattern, low)) for pattern in (
        r"\b(research|compare|investigate)\b",
        r"\b(build|implement|develop|code)\b",
        r"\b(write|draft|create content|prepare content)\b",
        r"\b(verify|review|test|check)\b",
    ))
    return action_hits >= 2


def _phase_task(phase: str, goal: str) -> str:
    if phase == "research":
        return f"Research the evidence, requirements, alternatives, risks and useful current information needed for this goal. Return concise findings and recommendations for the next specialist. Goal: {goal}"
    if phase == "coding":
        return f"Produce the technical architecture and implementation work needed for this goal. Use only the bounded upstream research supplied with this handoff. Keep implementation details in your own specialist workspace. Goal: {goal}"
    if phase == "writing":
        return f"Create the writing/content deliverable needed for this goal using only the bounded upstream findings supplied with this handoff. Goal: {goal}"
    return f"Verify the previous specialist deliverable against the original goal. Identify defects, unsupported claims, missing requirements and concrete corrections. Return a clear pass/needs-work verdict. Goal: {goal}"


def build_autopilot_plan(goal: str, manager: dict[str, Any]) -> dict[str, Any] | None:
    if not _autopilot_worthy(goal):
        return None
    phases = _phase_names(goal)
    if len(phases) < 2:
        return None
    used: set[str] = set()
    steps = []
    missing = []
    for phase in phases:
        agent = _best_agent(phase, goal, str(manager["id"]), used)
        if not agent:
            missing.append(phase)
            continue
        used.add(str(agent["id"]))
        steps.append({"phase": phase, "agent": agent, "task": _phase_task(phase, goal)})
    if len(steps) < 2:
        return None
    return {"goal": goal.strip(), "manager": manager, "steps": steps, "missing": missing}


def _bounded_dependency(result: str, limit: int = 7000) -> str:
    text = str(result or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n[Upstream result truncated for bounded handoff context.]"


def _configure_team_job(job_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    from agentie.core import team_orchestrator as team

    phase_by_agent = {str(step["agent"]["id"]): step for step in plan["steps"]}

    def apply(job: dict[str, Any]) -> None:
        job["autopilot"] = True
        job["autopilot_manager_id"] = plan["manager"]["id"]
        job["autopilot_manager_name"] = plan["manager"]["name"]
        job["autopilot_goal"] = plan["goal"]
        job["autopilot_missing"] = list(plan.get("missing") or [])
        ordered = []
        previous = None
        for handoff in job.get("handoffs", []):
            step = phase_by_agent.get(str(handoff.get("to_agent_id")))
            if not step:
                continue
            handoff["task"] = step["task"]
            handoff["autopilot_phase"] = step["phase"]
            handoff["depends_on"] = [previous] if previous else []
            handoff.setdefault("context", {})["task"] = step["task"]
            handoff["context"]["autopilot_goal"] = plan["goal"]
            ordered.append(handoff["id"])
            previous = handoff["id"]
        job["autopilot_order"] = ordered

    return team._mutate(job_id, apply) or get_team_job(job_id) or {}


def _fail_downstream(job_id: str, failed_id: str) -> None:
    from agentie.core import team_orchestrator as team

    def apply(job: dict[str, Any]) -> None:
        seen = False
        completed = [h for h in job.get("handoffs", []) if h.get("status") == "completed"]
        for handoff in job.get("handoffs", []):
            if handoff.get("id") == failed_id:
                seen = True
                continue
            if seen and handoff.get("status") == "queued":
                handoff["status"] = "failed"
                handoff["error"] = "Dependency failed"
                handoff["finished_at"] = team._now()
                handoff["progress_summary"] = "Not started because an earlier Autopilot stage failed."
        job["status"] = "partial" if completed else "failed"
        job["finished_at"] = team._now()
        outputs = [f"{h.get('to_agent_name')}:\n{h.get('result')}" for h in job.get("handoffs", []) if h.get("status") == "completed" and h.get("result")]
        job["final_output"] = "\n\n---\n\n".join(outputs) if outputs else None

    team._mutate(job_id, apply)


def _inject_dependency(job_id: str, handoff_id: str, previous: dict[str, Any], goal: str) -> None:
    from agentie.core import team_orchestrator as team
    upstream = _bounded_dependency(previous.get("result") or "")
    phase = previous.get("autopilot_phase") or "previous specialist"

    def apply(job: dict[str, Any]) -> None:
        for handoff in job.get("handoffs", []):
            if handoff.get("id") != handoff_id:
                continue
            base = str(handoff.get("task") or "")
            handoff.setdefault("context", {})["scoped_brief"] = (
                f"Original manager goal:\n{goal}\n\nYour bounded assignment:\n{base}\n\n"
                f"Upstream {phase} result (only this dependency is shared):\n{upstream}"
            )
            break

    team._mutate(job_id, apply)


def _controller(job_id: str) -> None:
    try:
        job = get_team_job(job_id)
        if not job:
            return
        order = list(job.get("autopilot_order") or [])
        previous: dict[str, Any] | None = None
        for handoff_id in order:
            current = get_team_job(job_id)
            if not current:
                return
            handoff = next((h for h in current.get("handoffs", []) if h.get("id") == handoff_id), None)
            if not handoff:
                continue
            if previous:
                if previous.get("status") != "completed":
                    _fail_downstream(job_id, str(previous.get("id")))
                    return
                _inject_dependency(job_id, handoff_id, previous, str(current.get("autopilot_goal") or current.get("task") or ""))
            # The previous team-worker thread may remain alive for a few milliseconds
            # after persisting its terminal handoff state. Retry the start until this
            # handoff actually leaves queued, avoiding a sequential-stage deadlock.
            while True:
                start_team_job(job_id, {handoff_id})
                time.sleep(0.08)
                started = get_team_job(job_id)
                if not started:
                    return
                observed = next((h for h in started.get("handoffs", []) if h.get("id") == handoff_id), None)
                if observed and observed.get("status") != "queued":
                    break
            while True:
                time.sleep(0.12)
                latest = get_team_job(job_id)
                if not latest:
                    return
                observed = next((h for h in latest.get("handoffs", []) if h.get("id") == handoff_id), None)
                if observed and observed.get("status") in {"completed", "failed", "cancelled"}:
                    previous = observed
                    break
            if previous and previous.get("status") != "completed":
                _fail_downstream(job_id, handoff_id)
                return
    finally:
        with _CONTROLLER_LOCK:
            _CONTROLLERS.pop(job_id, None)


def start_autopilot_job(plan: dict[str, Any], session_id: str | None = None) -> dict[str, Any]:
    agents = [step["agent"] for step in plan["steps"]]
    job = create_team_job(plan["goal"], agents, requested_by=str(plan["manager"]["id"]))
    job = _configure_team_job(job["id"], plan)
    if session_id:
        set_context(session_id, "active_team_job_id", job["id"])
        set_context(session_id, "active_team_job_task", plan["goal"])
    thread = threading.Thread(target=_controller, args=(job["id"],), daemon=True, name=f"agentie-autopilot-{job['id']}")
    with _CONTROLLER_LOCK:
        _CONTROLLERS[job["id"]] = thread
    thread.start()
    return get_team_job(job["id"]) or job


def maybe_manager_autopilot(message: str, session_id: str | None) -> dict[str, Any] | None:
    manager = _active_manager(session_id)
    if not manager:
        return None
    text = " ".join(str(message or "").strip().split())
    lower = text.casefold().strip(" .?!")
    if not text or re.match(r"^(show|list|delete|remove|rename|remember|set|create an agent|make an agent|delegate|handoff|hand off|have |ask |tell |retry|pause|resume|cancel)\b", lower):
        return None
    plan = build_autopilot_plan(text, manager)
    if not plan:
        return None
    job = start_autopilot_job(plan, session_id)
    card = team_job_card(job)
    card["autopilot"] = True
    card["manager"] = {"id": manager["id"], "name": manager["name"], "role": manager["role"]}
    card["phases"] = [
        {"phase": step["phase"], "agent": step["agent"]["name"], "role": step["agent"]["role"], "task": step["task"]}
        for step in plan["steps"]
    ]
    card["missing_specialties"] = plan.get("missing") or []
    names = " → ".join(f"{step['agent']['name']} ({step['phase']})" for step in plan["steps"])
    message = f"Manager Autopilot started {job['id']}: {names}. I’ll pass only the bounded result each next specialist needs."
    if plan.get("missing"):
        message += " Missing specialist coverage: " + ", ".join(plan["missing"]) + "."
    return {"message": message, "card": card}