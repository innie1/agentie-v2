from __future__ import annotations

import re
from typing import Any

from agentie.core.agent_matching import agent_identity_text
from agentie.core.agent_registry import get_agent
from agentie.core.skill_library import _TEMPLATES as STARTER_TEMPLATES
from agentie.core.skill_library import assign_skill, install_template
from agentie.core.skill_portability import export_skill
from agentie.core.workflow_skills import create_workflow_skill, get_workflow_skill, list_workflow_skills, skill_card

_CURATED: dict[str, dict[str, Any]] = {
    "meeting-prep": {
        "name": "Meeting Prep",
        "description": "Build a focused meeting brief from the available context, open questions and decisions needed.",
        "when_to_use": "Before an important meeting, review or decision call.",
        "required_inputs": ["meeting goal"],
        "required_access": [],
        "steps": ["Collect relevant current context", "List known facts and unresolved questions", "Identify decisions needed", "Prepare a short agenda and talking points", "Flag anything that needs verification"],
        "decision_rules": ["Do not invent context that is not available", "Separate facts from proposed talking points"],
        "expected_output": "A concise meeting brief with agenda, facts, questions and decisions needed.",
        "validation_rules": ["Every factual claim is grounded in available context"],
        "tags": ["meetings", "planning", "briefing"],
    },
    "lead-research": {
        "name": "Lead Research",
        "description": "Research a prospect or account and turn verified findings into a useful outreach brief.",
        "when_to_use": "When an agent needs background before contacting a prospect or account.",
        "required_inputs": ["lead or company"],
        "required_access": ["research"],
        "steps": ["Confirm the target identity", "Gather current public evidence", "Identify likely needs and relevant context", "Separate verified facts from inference", "Recommend an outreach angle without sending anything"],
        "decision_rules": ["Never invent private information", "Sending outreach remains approval-bound"],
        "expected_output": "A sourced lead brief with verified facts, likely needs and a recommended outreach angle.",
        "validation_rules": ["Material facts are sourced or clearly marked unverified"],
        "tags": ["sales", "research", "leads"],
    },
    "invoice-review": {
        "name": "Invoice Review",
        "description": "Check an invoice for totals, anomalies, missing information and approval risks before payment.",
        "when_to_use": "Before an invoice is approved or paid.",
        "required_inputs": ["invoice"],
        "required_access": ["files"],
        "steps": ["Read invoice fields and line items", "Recalculate totals", "Check dates, parties and references", "Flag anomalies or missing evidence", "Return recommendation without paying"],
        "decision_rules": ["Payment always requires the normal approval path", "Do not approve unexplained mismatches"],
        "expected_output": "An invoice review with totals, anomalies, risks and payment recommendation.",
        "validation_rules": ["Calculated totals reconcile or the mismatch is explicit"],
        "tags": ["finance", "invoice", "review"],
    },
    "file-intake": {
        "name": "File Intake",
        "description": "Inspect a newly received file, classify it, extract useful context and route the next action safely.",
        "when_to_use": "When a new document or file arrives for processing.",
        "required_inputs": ["file"],
        "required_access": ["files"],
        "steps": ["Inspect file type and metadata", "Extract readable content when supported", "Summarize purpose and important fields", "Identify the likely owner or workflow", "Flag unsafe or unsupported content instead of guessing"],
        "decision_rules": ["Never claim unreadable content was reviewed", "Keep extracted secrets out of shared summaries unless required"],
        "expected_output": "A file intake summary with classification, key information and recommended next owner/action.",
        "validation_rules": ["Summary matches actual extracted content"],
        "tags": ["files", "documents", "intake"],
    },
    "content-qa": {
        "name": "Content QA",
        "description": "Review content for factual consistency, clarity, requirements, risky claims and publish readiness.",
        "when_to_use": "Before important content is published or sent externally.",
        "required_inputs": ["content", "requirements"],
        "required_access": [],
        "steps": ["Extract requirements and intended audience", "Check structure and clarity", "Flag unsupported or risky factual claims", "Check required names, dates, links and calls to action", "Return fixes and a readiness recommendation"],
        "decision_rules": ["Publishing is not authorized by a QA pass", "Unverified facts block a fully-ready recommendation when material"],
        "expected_output": "A prioritized QA report and publish-readiness recommendation.",
        "validation_rules": ["Every critical issue maps to a specific requirement or claim"],
        "tags": ["content", "quality", "publishing"],
    },
    "calendar-brief": {
        "name": "Calendar Brief",
        "description": "Prepare a concise brief around an upcoming calendar event using available company and project context.",
        "when_to_use": "When an upcoming meeting or calendar event needs preparation.",
        "required_inputs": ["calendar event"],
        "required_access": ["planning"],
        "steps": ["Read event title, time and participants from supplied context", "Find relevant scoped project/company context", "List objectives and open decisions", "Prepare talking points and follow-ups", "Flag missing information"],
        "decision_rules": ["Do not infer attendee intent as fact", "Do not change the calendar without explicit permission"],
        "expected_output": "A short event brief with objectives, context, questions and follow-ups.",
        "validation_rules": ["Event details match supplied event context"],
        "tags": ["calendar", "meetings", "planning"],
    },
}

_STOP = {"the", "and", "for", "with", "that", "this", "from", "into", "when", "agent", "skill", "work", "user", "their", "your"}


def _words(value: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9]+", str(value or "").casefold()) if len(x) > 2 and x not in _STOP}


def _tags(item: dict[str, Any]) -> list[str]:
    explicit = [str(x).casefold() for x in item.get("tags") or [] if str(x).strip()]
    access = [str(x).casefold() for x in item.get("required_access") or [] if str(x).strip()]
    words = sorted(_words(f"{item.get('name','')} {item.get('description','')}"))[:6]
    return list(dict.fromkeys(explicit + access + words))[:10]


def _all_curated() -> dict[str, dict[str, Any]]:
    combined: dict[str, dict[str, Any]] = {}
    for key, value in STARTER_TEMPLATES.items():
        combined[f"starter:{key}"] = {**value, "source": "agentie_curated", "template_id": key, "catalog_id": f"starter:{key}"}
    for key, value in _CURATED.items():
        combined[f"market:{key}"] = {**value, "source": "agentie_curated", "template_id": key, "catalog_id": f"market:{key}"}
    return combined


def _score(query: str, item: dict[str, Any], agent_text: str = "") -> int:
    hay = _words(" ".join([str(item.get("name") or ""), str(item.get("description") or ""), str(item.get("when_to_use") or ""), " ".join(map(str, item.get("required_access") or [])), " ".join(map(str, item.get("tags") or []))]))
    query_words = _words(query)
    identity_words = _words(agent_text)
    score = len(query_words & hay) * 5 + len(identity_words & hay) * 2
    name = str(item.get("name") or "").casefold()
    if query and str(query).casefold() in name:
        score += 6
    return score


def search_marketplace(query: str = "", *, agent_id: str | None = None) -> dict[str, Any]:
    agent = get_agent(agent_id) if agent_id else None
    agent_text = agent_identity_text(agent) if agent else ""
    items: list[dict[str, Any]] = []
    for cid, raw in _all_curated().items():
        installed = bool(get_workflow_skill(raw["name"]))
        score = _score(query, raw, agent_text)
        items.append({
            "id": cid,
            "name": raw["name"],
            "description": raw.get("description") or "",
            "when_to_use": raw.get("when_to_use") or "",
            "required_access": list(raw.get("required_access") or []),
            "tags": _tags(raw),
            "source": "agentie_curated",
            "installed": installed,
            "score": score,
            "recommended": bool(agent and score > 0),
        })
    for skill in list_workflow_skills():
        score = _score(query, skill, agent_text)
        items.append({
            "id": f"installed:{skill['id']}",
            "skill_id": skill["id"],
            "name": skill["name"],
            "description": skill.get("description") or "",
            "when_to_use": skill.get("when_to_use") or "",
            "required_access": list(skill.get("required_access") or []),
            "tags": _tags(skill),
            "source": "installed",
            "installed": True,
            "status": skill.get("status"),
            "score": score,
            "recommended": bool(agent and score > 0),
        })
    if query or agent:
        items.sort(key=lambda x: (-int(x.get("score") or 0), x["name"].casefold()))
    else:
        items.sort(key=lambda x: (0 if x["source"] == "agentie_curated" else 1, x["name"].casefold()))
    if query:
        items = [x for x in items if int(x.get("score") or 0) > 0]
    return {
        "items": items,
        "query": query,
        "agent": {"id": agent["id"], "name": agent["name"], "job": agent.get("role")} if agent else None,
        "catalog_kind": "agentie_curated_local",
        "message": "This catalog contains Agentie-curated/local reusable Skills and your installed Skills. It is not presented as a remote community marketplace.",
    }


def _create_curated(template_id: str) -> dict[str, Any]:
    raw = _CURATED.get(template_id)
    if not raw:
        raise ValueError("Curated Skill was not found.")
    existing = get_workflow_skill(raw["name"])
    if existing:
        return existing
    payload = {k: v for k, v in raw.items() if k != "tags"}
    return create_workflow_skill(**payload, status="draft", approval_boundaries=["Use Agentie's normal approval path for consequential actions."], failure_handling="Stop on a real failure, report it clearly, and ask for missing input or permission rather than pretending completion.")


def install_marketplace_item(catalog_id: str) -> dict[str, Any]:
    value = str(catalog_id or "")
    if value.startswith("starter:"):
        return install_template(value.split(":", 1)[1])
    if value.startswith("market:"):
        return _create_curated(value.split(":", 1)[1])
    if value.startswith("installed:"):
        skill = get_workflow_skill(value.split(":", 1)[1])
        if skill:
            return skill
    raise ValueError("Skill marketplace item was not found.")


def assign_marketplace_item(catalog_id: str, agent_id: str) -> dict[str, Any]:
    skill = install_marketplace_item(catalog_id)
    return assign_skill(skill["id"], agent_id)


def share_installed_skill(skill_id_or_name: str) -> dict[str, Any]:
    result = export_skill(skill_id_or_name)
    return {"skill": skill_card(result["skill"]), "card": result["card"]}
