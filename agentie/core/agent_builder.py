from __future__ import annotations

import re
from typing import Any

from agentie.core.mcp_catalog import presets as mcp_presets
from agentie.core.mcp_client import list_servers
from agentie.core.skill_registry import list_skills

_STOP={"a","an","and","are","as","at","be","by","for","from","in","is","it","my","of","on","or","our","that","the","their","this","to","user","with","who","will","agent","bot","employee","work","job"}
_DEFAULT_APPROVAL_POLICY={
    "send_external":"approval",
    "publish":"approval",
    "delete_or_overwrite":"approval",
    "purchase_or_payment":"approval",
    "financial_transfer":"approval",
    "permission_change":"approval",
    "production_change":"approval",
    "accept_legal_terms":"approval",
    "safe_read":"automatic",
    "draft_or_recommend":"automatic",
}


def _clean(value: str, limit: int = 1200) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _words(value: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", str(value or "").casefold()) if len(w)>1 and w not in _STOP}


def _score(query: str, item: dict[str, Any]) -> int:
    q=_words(query)
    if not q:return 0
    fields=[item.get("name"),item.get("description")," ".join(map(str,item.get("capabilities") or [])),item.get("requires")]
    text=" ".join(str(x or "") for x in fields).casefold()
    words=_words(text)
    score=len(q & words)*3
    for token in q:
        if token in text:score+=1
    return score


def recommend_skills(description: str, limit: int = 6) -> list[dict[str, Any]]:
    scored=[]
    for skill in list_skills():
        score=_score(description,skill)
        if score>0:scored.append((score,skill))
    scored.sort(key=lambda x:(-x[0],str(x[1].get("name") or x[1].get("id") or "").casefold()))
    return [{"id":str(item.get("id")),"name":str(item.get("name") or item.get("id")),"description":str(item.get("description") or ""),"score":score} for score,item in scored[:max(1,limit)]]


def recommend_plugins(description: str, limit: int = 6) -> list[dict[str, Any]]:
    installed={str(x.get("name") or "").casefold() for x in list_servers()}
    scored=[]
    for preset in mcp_presets():
        score=_score(description,preset)
        if score>0:scored.append((score,preset))
    scored.sort(key=lambda x:(-x[0],str(x[1].get("name") or x[1].get("id") or "").casefold()))
    return [{"id":str(item.get("id")),"name":str(item.get("name") or item.get("id")),"description":str(item.get("description") or ""),"installed":str(item.get("id") or "").casefold() in installed,"score":score} for score,item in scored[:max(1,limit)]]


def _sentences(description: str) -> list[str]:
    parts=[_clean(x,400) for x in re.split(r"[\n;]+|(?<=[.!?])\s+",str(description or ""))]
    return [x.strip(" .") for x in parts if len(x.strip(" ."))>=4]


def draft_agent_spec(description: str, *, name: str = "", job: str = "") -> dict[str, Any]:
    description=_clean(description,5000)
    if not description:raise ValueError("Describe what this agent should own or be responsible for.")
    sentences=_sentences(description)
    job_text=_clean(job or (sentences[0] if sentences else description),500)
    goal=f"Own this area of work and achieve the outcome described by the user: {job_text}"
    responsibilities=[]
    for sentence in sentences[1:6]:
        if sentence.casefold() not in {x.casefold() for x in responsibilities}:responsibilities.append(sentence)
    if not responsibilities:
        responsibilities=[
            "Own the work described in this job and carry it through to a useful result",
            "Use assigned skills, plugins, files, knowledge and the shared computer only within granted permissions",
            "Report progress, blockers, meaningful risks and recommendations clearly",
        ]
    working_style="Proactive, reliable, clear about uncertainty, and willing to recommend a better approach when evidence supports it"
    instructions=(
        f"Job ownership: {job_text}.\n"
        "Work from the user's configured goal, responsibilities, knowledge, skills, plugins and approval boundaries. "
        "Do not assume a predefined profession or department beyond what the user configured. "
        "Use the least costly real capability that can complete the work, and never claim an action succeeded unless it actually did."
    )
    return {
        "name":_clean(name,120),
        "job":job_text,
        "description":description,
        "goal":goal,
        "working_style":working_style,
        "responsibilities":responsibilities,
        "instructions":instructions,
        "skills":recommend_skills(description),
        "plugins":recommend_plugins(description),
        "approval_policy":dict(_DEFAULT_APPROVAL_POLICY),
        "memory_policy":{"private_context":True,"company_knowledge":"read","project_knowledge":"scoped"},
        "can_delegate":False,
        "manager_id":None,
        "runtime_profile":"general",
    }


def normalize_create_spec(spec: dict[str, Any]) -> dict[str, Any]:
    name=_clean(spec.get("name") or "",120)
    if not name:raise ValueError("Agent name is required.")
    job=_clean(spec.get("job") or spec.get("role") or "",500)
    if not job:raise ValueError("Describe the agent's job or area of ownership.")
    responsibilities=[]
    for value in spec.get("responsibilities") or []:
        item=_clean(value,400)
        if item and item.casefold() not in {x.casefold() for x in responsibilities}:responsibilities.append(item)
    selected_skills=[]
    for value in spec.get("skills") or []:
        sid=str(value.get("id") if isinstance(value,dict) else value).strip().lower()
        if sid:selected_skills.append(sid)
    selected_plugins=[]
    for value in spec.get("plugins") or []:
        pid=str(value.get("id") if isinstance(value,dict) else value).strip().lower()
        if pid:selected_plugins.append(pid)
    approval=dict(_DEFAULT_APPROVAL_POLICY);approval.update({str(k):str(v) for k,v in dict(spec.get("approval_policy") or {}).items()})
    return {
        "name":name,
        "role":job,
        "purpose":_clean(spec.get("description") or job,1600),
        "goal":_clean(spec.get("goal") or f"Own and complete: {job}",1600),
        "personality":_clean(spec.get("working_style") or "Proactive, reliable, and clear about uncertainty",800),
        "responsibilities":responsibilities,
        "manual_instructions":str(spec.get("instructions") or "").strip()[:12000],
        "skills":sorted(set(selected_skills)),
        "plugins":sorted(set(selected_plugins)),
        "approval_policy":approval,
        "memory_policy":dict(spec.get("memory_policy") or {}),
        "manager_id":spec.get("manager_id") or None,
        "can_delegate":bool(spec.get("can_delegate")),
        # Runtime profile is deliberately internal. New user-created agents are
        # not classified into predefined professions.
        "runtime_profile":"general",
    }
