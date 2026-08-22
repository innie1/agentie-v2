from __future__ import annotations

import re
from typing import Any

from agentie.core.agent_matching import best_agent,match_score,task_signature
from agentie.core.agent_registry import get_agent
from agentie.core.memory_store import get_context,get_memory,set_context,set_memory
from agentie.core.team_orchestrator import create_team_job,start_team_job,team_job_card


def _active_agent_from_session(session_id:str|None)->dict[str,Any]|None:
    m=re.match(r"^agent:(agt_[a-z0-9]+):",str(session_id or ""),re.I)
    return get_agent(m.group(1)) if m else None


def _routing_key(from_agent_id:str,signature:str)->str:
    # Legacy task-signature preference key retained for older saved preferences.
    return f"handoff:{from_agent_id}:{signature}"


def _agent_preference_key(from_agent_id:str,to_agent_id:str)->str:
    """Preference for work that the configured matcher selects for this agent.

    This is intentionally keyed by the actual user-created agent rather than a
    baked-in specialty label such as writing/research/coding. If future work is
    again best matched to the same configured agent, an "Always accept" choice
    can be honored without recreating hidden profession classes.
    """
    return f"handoff:{from_agent_id}:agent:{to_agent_id}"


def best_specialist(task:str,exclude_id:str|None=None)->dict[str,Any]|None:
    return best_agent(task,exclude_id=exclude_id,min_score=.16)


def _start_handoff(current:dict[str,Any],specialist:dict[str,Any],task:str,session_id:str|None,signature:str,always:bool=False)->dict[str,Any]:
    if always:
        metadata={"kind":"handoff_preference","from_agent_id":current["id"],"task_signature":signature,"to_agent_id":specialist["id"]}
        # New platform preference: future work that the configured matcher again
        # assigns to this same agent can auto-route. Keep the exact-signature row
        # too so older saved behavior remains compatible.
        set_memory("routing",_agent_preference_key(str(current["id"]),str(specialist["id"])),str(specialist["id"]),metadata)
        set_memory("routing",_routing_key(str(current["id"]),signature),str(specialist["id"]),metadata)
    job=create_team_job(task,[specialist],requested_by=str(current["id"]));start_team_job(job["id"])
    if session_id:
        set_context(session_id,"active_team_job_id",job["id"]);set_context(session_id,"active_team_job_task",job["task"]);set_context(session_id,"pending_handoff",None)
    message=f"Handed this task to {specialist['name']} ({specialist['role']}) as {job['id']}."
    if always:message+=f" I’ll prefer {specialist['name']} whenever future work is again best matched to that configured agent, unless you change that preference."
    return {"message":message,"card":{"type":"agent_handoff","from_agent":{"id":current["id"],"name":current["name"],"role":current["role"]},"to_agent":{"id":specialist["id"],"name":specialist["name"],"role":specialist["role"]},"reason":"Best match for the configured job, responsibilities and capabilities","team_job":team_job_card(job)}}


def maybe_auto_delegate(message:str,session_id:str|None)->dict[str,Any]|None:
    """Offer a handoff only when another user-created agent is a better match.

    There are deliberately no baked-in research/coding/writing/planning classes here.
    Matching is based on the jobs, responsibilities, skills and plugins the user
    actually configured for their agents.
    """
    current=_active_agent_from_session(session_id)
    if not current:return None
    lower=" ".join(str(message or "").casefold().strip().split()).strip(" .?!")
    accept=lower in {"accept handoff","accept that handoff","accept this handoff","accept"}
    always=lower in {"always accept handoff","always accept that handoff","always accept this handoff","always accept"}
    if accept or always:
        pending=get_context(session_id,"pending_handoff",None) if session_id else None
        if not isinstance(pending,dict) or str(pending.get("from_agent_id"))!=str(current.get("id")):return {"message":"There isn’t a pending handoff to accept.","card":None}
        specialist=get_agent(str(pending.get("to_agent_id") or ""))
        if not specialist:return {"message":"The proposed agent no longer exists.","card":None}
        task=str(pending.get("task") or "").strip();signature=str(pending.get("task_signature") or task_signature(task))
        if not task:return {"message":"The pending handoff no longer has a task to run.","card":None}
        return _start_handoff(current,specialist,task,session_id,signature,always=always)
    from agentie.core.manager_autopilot import maybe_manager_autopilot
    autopilot=maybe_manager_autopilot(message,session_id)
    if autopilot is not None:return autopilot
    if re.match(r"^(delegate|hand off|handoff|have |ask |tell |create |make |add |delete |remove |show |list |retry |set |update |change )",lower):return None
    candidate=best_agent(message,exclude_id=str(current.get("id")),min_score=.18)
    if not candidate:return None
    current_score=match_score(message,current);candidate_score=match_score(message,candidate)
    # Do not manufacture handoffs when the selected agent is already a credible
    # owner. Another agent must be materially better.
    if candidate_score<max(.18,current_score+.08):return None
    signature=task_signature(message)
    # New platform preference follows the actual configured agent selected by
    # matching. Fall back to the old exact-task signature for existing data.
    preferred_id=get_memory("routing",_agent_preference_key(str(current["id"]),str(candidate["id"])))
    if not preferred_id:preferred_id=get_memory("routing",_routing_key(str(current["id"]),signature))
    if preferred_id and str(preferred_id)==str(candidate.get("id")):
        return _start_handoff(current,candidate,message,session_id,signature,always=False)
    if session_id:set_context(session_id,"pending_handoff",{"from_agent_id":current["id"],"to_agent_id":candidate["id"],"task":message.strip(),"task_signature":signature})
    return {"message":f"This looks better matched to {candidate['name']} ({candidate['role']}).","card":{"type":"agent_handoff_proposal","from_agent":{"id":current["id"],"name":current["name"],"role":current["role"]},"to_agent":{"id":candidate["id"],"name":candidate["name"],"role":candidate["role"]},"task":message.strip(),"specialty":signature,"reason":"Matched configured ownership, responsibilities, skills and tools","actions":[{"action":"accept_handoff","label":"Accept"},{"action":"always_accept_handoff","label":"Always accept"}]}}
