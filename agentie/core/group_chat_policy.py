from __future__ import annotations

import re
from typing import Any

from agentie.core import agent_threads, runner, team_orchestrator
from agentie.core.agent_prompt import agent_from_session

_INSTALLED = False
_ORIGINAL_THREAD_CREATE_TEAM_JOB = None
_ORIGINAL_RUN_AGENT = None
_ORIGINAL_VISIBLE_REPLY = None


def wants_detailed_response(task: str) -> bool:
    text = " ".join(str(task or "").strip().split()).casefold()
    return bool(
        re.search(
            r"\b(?:detailed|in detail|deep dive|deep analysis|full report|full analysis|comprehensive|thorough|step[- ]by[- ]step|long[- ]form|write (?:me )?a report|detailed comparison)\b",
            text,
        )
    )


def _strip_internal_scaffolding(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return text
    # Internal worker summaries are useful in activity/audit surfaces but should
    # never leak into the visible group conversation.
    text = re.split(
        r"(?im)^\s*#{0,6}\s*(?:\*{0,2})?(?:(?:executive|final|concise|worker|agent)\s+)?handoff summary\b",
        text,
        maxsplit=1,
    )[0].strip()
    text = re.sub(
        r"(?im)^\s*#{1,6}\s*(?:\*{0,2})?(?:deliverable|response|answer)\s*:?[ \t]*\n?",
        "",
        text,
        count=1,
    ).strip()
    text = re.sub(r"(?m)^\s*---+\s*$", "", text).strip()
    return text


def clean_group_output(value: str, *, detailed: bool = False) -> str:
    text = _strip_internal_scaffolding(value)
    if not text:
        return "I don't have a useful answer yet."
    if detailed:
        return text[:12000]
    # The prompt is the primary length control. This is a UI-safety backstop so
    # a model cannot turn an ordinary "give your view" request into a huge report.
    limit = 850
    if len(text) <= limit:
        return text
    candidate = text[:limit]
    cut = max(candidate.rfind(". "), candidate.rfind("! "), candidate.rfind("? "), candidate.rfind("\n"))
    if cut >= 300:
        candidate = candidate[: cut + 1]
    return candidate.rstrip() + "…"


def _group_prompt(agent: dict[str, Any] | None, task: str, *, chat: bool, detailed: bool) -> str:
    name = str((agent or {}).get("name") or "Agent")
    role = str((agent or {}).get("role") or "team member")
    if chat:
        length_rule = "Reply naturally in 1-3 short sentences."
    elif detailed:
        length_rule = "The user explicitly asked for detail, so you may give a structured answer, but keep it relevant and avoid filler."
    else:
        length_rule = "Give your view concisely: usually 2-5 sentences or at most 4 short bullets. Do not write a full report."
    return (
        f"You are {name}, the {role}, replying as one participant inside an Agentie group chat.\n"
        f"Give YOUR role-specific view. Do not impersonate the other agents and do not synthesize a full-team report. {length_rule}\n"
        "Answer the user's actual question directly. If a recommendation is appropriate, state your recommendation and the most important reason or risk.\n"
        "Do not output internal workflow headings or metadata such as Deliverable, Handoff Summary, Executive Handoff Summary, worker status, or handoff notes.\n"
        "Be strict about evidence: do not call a claim verified/factual unless it was actually verified in this run or is stable general knowledge. "
        "Do not invent or present specific current prices, percentages, market sizes, rates, legal requirements, business costs, or availability as verified. "
        "If a number is only a rough assumption, label it as an estimate. If current/local evidence matters and you did not retrieve it, say what needs verification.\n"
        "Use light Markdown only when it improves readability. Avoid tables unless the user explicitly asked for a detailed comparison/report.\n\n"
        f"User message: {task}"
    )


def install_group_chat_policy() -> None:
    """Install a narrow policy around the existing Team Job and model runtime.

    Only jobs created through agent_threads by the user are marked as group-chat
    work. Generic Team Jobs, project handoffs and agent-to-agent delegation keep
    their existing behavior.
    """
    global _INSTALLED, _ORIGINAL_THREAD_CREATE_TEAM_JOB, _ORIGINAL_RUN_AGENT, _ORIGINAL_VISIBLE_REPLY
    if _INSTALLED:
        return
    _INSTALLED = True

    _ORIGINAL_THREAD_CREATE_TEAM_JOB = agent_threads.create_team_job
    _ORIGINAL_RUN_AGENT = runner.run_agent
    _ORIGINAL_VISIBLE_REPLY = agent_threads._visible_agent_reply

    def group_thread_create_team_job(task, agents, requested_by="user", project_id=None, interaction_mode="task"):
        job = _ORIGINAL_THREAD_CREATE_TEAM_JOB(
            task,
            agents,
            requested_by=requested_by,
            project_id=project_id,
            interaction_mode=interaction_mode,
        )
        if str(requested_by).casefold() == "user":
            detail = "detailed" if wants_detailed_response(str(task)) else "concise"

            def mark(value):
                value["surface"] = "group_chat"
                value["response_detail"] = detail

            updated = team_orchestrator._mutate(job["id"], mark)
            if updated:
                return updated
        return job

    async def policy_run_agent(message: str, agent_type: str = "general", session_id: str | None = None) -> str:
        match = re.search(r"handoff:(team_[a-z0-9]+)", str(session_id or ""), re.I)
        if not match:
            return await _ORIGINAL_RUN_AGENT(message, agent_type, session_id)
        job = team_orchestrator.get_team_job(match.group(1))
        if not job or str(job.get("surface") or "") != "group_chat":
            return await _ORIGINAL_RUN_AGENT(message, agent_type, session_id)
        task = str(job.get("task") or "")
        chat = str(job.get("interaction_mode") or "task") == "chat"
        detailed = str(job.get("response_detail") or "concise") == "detailed"
        agent = agent_from_session(session_id)
        prompt = _group_prompt(agent, task, chat=chat, detailed=detailed)
        output = await _ORIGINAL_RUN_AGENT(prompt, agent_type, session_id)
        return clean_group_output(output, detailed=detailed)

    def visible_reply(value: str, mode: str = "task") -> str:
        base = _ORIGINAL_VISIBLE_REPLY(value, mode)
        return _strip_internal_scaffolding(base) or "Completed the assigned task."

    # agent_threads imported create_team_job directly, so patch only its local
    # reference. This deliberately does not alter generic team_orchestrator calls.
    agent_threads.create_team_job = group_thread_create_team_job
    runner.run_agent = policy_run_agent
    agent_threads._visible_agent_reply = visible_reply
