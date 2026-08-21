from __future__ import annotations

import re
from typing import Any

from agentie.core.agent_registry import get_agent, list_agents
from agentie.core.memory_store import get_context, get_memory, set_context, set_memory
from agentie.core.team_orchestrator import create_team_job, start_team_job, team_job_card

# Local deterministic specialty routing: no external model call is needed to decide a handoff.
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

def _routing_key(from_agent_id:str,specialty:str)->str:
    return f"handoff:{from_agent_id}:{specialty}"

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

def _start_handoff(current:dict[str,Any],specialist:dict[str,Any],task:str,session_id:str|None,specialty:str,always:bool=False)->dict[str,Any]:
    if always:
        set_memory("routing",_routing_key(str(current["id"]),specialty),str(specialist["id"]),{"kind":"handoff_preference","from_agent_id":current["id"],"specialty":specialty,"to_agent_id":specialist["id"]})
    job=create_team_job(task,[specialist],requested_by=str(current["id"]));start_team_job(job["id"])
    if session_id:
        set_context(session_id,"active_team_job_id",job["id"]);set_context(session_id,"active_team_job_task",job["task"]);set_context(session_id,"pending_handoff",None)
    message=f"Handed this task to {specialist['name']} ({specialist['role']}) as {job['id']}."
    if always:message+=f" I’ll automatically route future {specialty} work from {current['name']} to {specialist['name']} unless you change that preference."
    return {"message":message,"card":{"type":"agent_handoff","from_agent":{"id":current["id"],"name":current["name"],"role":current["role"]},"to_agent":{"id":specialist["id"],"name":specialist["name"],"role":specialist["role"]},"reason":f"Matched {specialty} specialty","team_job":team_job_card(job)}}

def maybe_auto_delegate(message:str,session_id:str|None)->dict[str,Any]|None:
    """Run Manager Autopilot for complex manager goals, otherwise use the normal specialty handoff flow."""
    current=_active_agent_from_session(session_id)
    if not current:return None
    lower=" ".join(message.casefold().strip().split()).strip(" .?!")
    accept=lower in {"accept handoff","accept that handoff","accept this handoff","accept"}
    always=lower in {"always accept handoff","always accept that handoff","always accept this handoff","always accept"}
    if accept or always:
        pending=get_context(session_id,"pending_handoff",None) if session_id else None
        if not isinstance(pending,dict) or str(pending.get("from_agent_id"))!=str(current.get("id")):
            return {"message":"There isn’t a pending handoff to accept.","card":None}
        specialist=get_agent(str(pending.get("to_agent_id") or ""))
        if not specialist:return {"message":"The proposed specialist no longer exists.","card":None}
        task=str(pending.get("task") or "").strip();specialty=str(pending.get("specialty") or _specialty_for_agent(specialist))
        if not task:return {"message":"The pending handoff no longer has a task to run.","card":None}
        return _start_handoff(current,specialist,task,session_id,specialty,always=always)
    # Explicit orchestration/registry commands are handled by their existing routers.
    if re.match(r"^(delegate|hand off|handoff|have |ask |tell |create |make |add |delete |remove |show |list |retry )",lower):return None
    # Manager Autopilot is intentionally inserted into the existing handoff router,
    # so the main request pipeline and all existing cards/events remain unchanged.
    from agentie.core.manager_autopilot import maybe_manager_autopilot
    autopilot=maybe_manager_autopilot(message,session_id)
    if autopilot is not None:return autopilot
    task_specialty,confidence=_specialty_for_task(message);current_specialty=_specialty_for_agent(current)
    if confidence<1 or task_specialty=="general" or task_specialty==current_specialty:return None
    specialist=best_specialist(message,current.get("id"))
    if not specialist:return None
    preferred_id=get_memory("routing",_routing_key(str(current["id"]),task_specialty))
    if preferred_id and str(preferred_id)==str(specialist.get("id")):
        return _start_handoff(current,specialist,message,session_id,task_specialty,always=False)
    if session_id:set_context(session_id,"pending_handoff",{"from_agent_id":current["id"],"to_agent_id":specialist["id"],"task":message.strip(),"specialty":task_specialty})
    return {"message":f"This task looks better suited to {specialist['name']} ({specialist['role']}).","card":{"type":"agent_handoff_proposal","from_agent":{"id":current["id"],"name":current["name"],"role":current["role"]},"to_agent":{"id":specialist["id"],"name":specialist["name"],"role":specialist["role"]},"task":message.strip(),"specialty":task_specialty,"reason":f"Matched {task_specialty} specialty","actions":[{"action":"accept_handoff","label":"Accept"},{"action":"always_accept_handoff","label":"Always accept"}]}}
