from __future__ import annotations

import re
from typing import Any

from agentie.core.agent_registry import get_agent, list_agents
from agentie.core.team_orchestrator import create_team_job, start_team_job, team_job_card

# Local deterministic specialty routing: no provider/API call is needed to decide a handoff.
SPECIALTIES={
    "research":{"research","researcher","analyst","market research","competitor","compare sources","investigate","verify","fact check","evidence"},
    "coding":{"cto","developer","coder","engineer","programmer","software","technical","code","bug","debug","github"},
    "writing":{"writer","content creator","content writer","copywriter","social media","blog","post","caption","script","copy"},
    "planning":{"ceo","manager","chief of staff","planner","strategy","plan","roadmap","coordinate","organize","delegate"},
}

def _words(value:str)->set[str]:
    return set(re.findall(r"[a-z0-9]+",str(value or "").casefold()))

def _specialty_for_agent(agent:dict[str,Any])->str:
    text=f"{agent.get('name','')} {agent.get('role','')} {agent.get('purpose','')} {agent.get('base','')}".casefold()
    best=(0,"general")
    for specialty,terms in SPECIALTIES.items():
        score=sum(2 if " " in term and term in text else 1 if term in _words(text) else 0 for term in terms)
        if score>best[0]:best=(score,specialty)
    return best[1]

def _specialty_for_task(task:str)->tuple[str,int]:
    text=task.casefold();words=_words(text);best=(0,"general")
    for specialty,terms in SPECIALTIES.items():
        score=sum(3 if " " in term and term in text else 1 if term in words else 0 for term in terms)
        if score>best[0]:best=(score,specialty)
    return best[1],best[0]

def _active_agent_from_session(session_id:str|None)->dict[str,Any]|None:
    m=re.match(r"^agent:(agt_[a-z0-9]+):",str(session_id or ""),re.I)
    return get_agent(m.group(1)) if m else None

def best_specialist(task:str,exclude_id:str|None=None)->dict[str,Any]|None:
    specialty,confidence=_specialty_for_task(task)
    if specialty=="general" or confidence<1:return None
    candidates=[]
    for agent in list_agents():
        if agent.get("id")==exclude_id:continue
        if _specialty_for_agent(agent)==specialty:
            text=f"{agent.get('name','')} {agent.get('role','')} {agent.get('purpose','')}".casefold();score=confidence+sum(1 for w in _words(task) if w in _words(text))
            candidates.append((score,agent))
    return sorted(candidates,key=lambda x:(-x[0],x[1]["name"].casefold()))[0][1] if candidates else None

def maybe_auto_delegate(message:str,session_id:str|None)->dict[str,Any]|None:
    """Auto-handoff only when a persistent agent is active and a clear different specialist exists."""
    current=_active_agent_from_session(session_id)
    if not current:return None
    # Explicit orchestration/registry commands are handled by their existing routers.
    lower=message.casefold().strip()
    if re.match(r"^(delegate|hand off|handoff|have |ask |tell |create |make |add |delete |remove |show |list |retry )",lower):return None
    task_specialty,confidence=_specialty_for_task(message);current_specialty=_specialty_for_agent(current)
    if confidence<1 or task_specialty=="general" or task_specialty==current_specialty:return None
    specialist=best_specialist(message,current.get("id"))
    if not specialist:return None
    job=create_team_job(message,[specialist],requested_by=str(current["id"]));start_team_job(job["id"])
    return {"message":f"This is better suited to {specialist['name']} ({specialist['role']}). I’m handing it over and will keep the work tracked as {job['id']}.","card":{"type":"agent_handoff","from_agent":{"id":current["id"],"name":current["name"],"role":current["role"]},"to_agent":{"id":specialist["id"],"name":specialist["name"],"role":specialist["role"]},"reason":f"Matched {task_specialty} specialty","team_job":team_job_card(job)}}
