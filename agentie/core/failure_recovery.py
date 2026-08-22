from __future__ import annotations

import re,uuid
from typing import Any

from agentie.core.agent_matching import rank_agents
from agentie.core.agent_registry import get_agent
from agentie.core.team_orchestrator import get_team_job

_TRANSIENT=re.compile(r"\b(?:timeout|timed out|rate limit|429|quota|usage limit|temporar|network|connection|unavailable|502|503|504)\b",re.I)
_PERMISSION=re.compile(r"\b(?:approval|required permission|not allowed|permission denied|needs approval|access denied)\b",re.I)
_INPUT=re.compile(r"\b(?:missing input|needs? (?:an? )?input|required input|provide .* value|secret field|password)\b",re.I)
_AGENT=re.compile(r"\b(?:agent no longer exists|agent was not found|missing agent)\b",re.I)
_TOOL=re.compile(r"\b(?:tool .* failed|plugin .* failed|mcp .* failed|browser .* failed|execution failed)\b",re.I)
def classify_failure(error:str)->str:
    text=str(error or "")
    if _PERMISSION.search(text):return "permission_or_approval"
    if _INPUT.search(text):return "missing_input"
    if _AGENT.search(text):return "missing_agent"
    if _TRANSIENT.search(text):return "transient"
    if _TOOL.search(text):return "tool_failure"
    return "unknown"
def recovery_policy(error:str,attempts:int=1)->dict[str,Any]:
    kind=classify_failure(error)
    if kind in {"permission_or_approval","missing_input"}:return {"classification":kind,"action":"ask_user","automatic":False,"reason":"The next step needs user authority or information; Agentie must not bypass it."}
    if attempts>=3:return {"classification":kind,"action":"stop","automatic":False,"reason":"The work has already failed repeatedly."}
    return {"classification":kind,"action":"replan","automatic":True,"reason":"Try another configured owner if one is a credible match."}
def _safe_context(handoff:dict[str,Any])->dict[str,Any]:
    source=dict(handoff.get("context") or {});out={"task":str(handoff.get("task") or "")}
    for key in ("project_id","scoped_brief","autopilot_goal","dependency_handoff_id","dependency_agent_name"):
        if key in source:out[key]=source[key]
    return out
def _candidate(task:str,failed_agent_id:str,attempted:set[str])->tuple[dict[str,Any]|None,float]:
    for row in rank_agents(task,exclude_id=failed_agent_id,limit=8):
        agent=row.get("agent");score=float(row.get("score") or 0)
        if not agent or str(agent.get("id")) in attempted or score<.16:continue
        return agent,score
    return None,0.0
def replan_failed_handoff(job_id:str,handoff_id:str)->dict[str,Any]:
    from agentie.core import team_orchestrator as team
    job=get_team_job(job_id)
    if not job:return {"action":"stop","reason":"Team job was not found."}
    manager=get_agent(str(job.get("autopilot_manager_id") or ""))
    if not manager or not bool((manager.get("permissions") or {}).get("delegate")):return {"action":"stop","reason":"Automatic replanning requires the job's explicitly authorized coordinator."}
    failed=next((x for x in job.get("handoffs") or [] if str(x.get("id"))==str(handoff_id)),None)
    if not failed or str(failed.get("status"))!="failed":return {"action":"stop","reason":"That handoff is not failed."}
    policy=recovery_policy(str(failed.get("error") or ""),int(failed.get("attempts") or 1))
    if not policy["automatic"]:return {**policy,"handoff_id":handoff_id}
    if failed.get("recovery_handoff_id"):return {"action":"already_replanned","handoff_id":failed.get("recovery_handoff_id")}
    attempted={str(manager["id"])}|{str(x.get("to_agent_id") or "") for x in job.get("handoffs") or [] if x.get("recovery_of")==handoff_id or str(x.get("id"))==str(handoff_id)}
    agent,score=_candidate(str(failed.get("task") or job.get("task") or ""),str(failed.get("to_agent_id") or ""),attempted)
    if not agent:return {**policy,"action":"ask_user","automatic":False,"reason":"No other configured agent is a strong enough match for the failed bounded task."}
    new_id="ho_"+uuid.uuid4().hex[:8];now=team._now();replacement={"id":new_id,"from":manager["id"],"to_agent_id":agent["id"],"to_agent_name":agent["name"],"task":str(failed.get("task") or ""),"context":_safe_context(failed),"status":"queued","result":None,"error":None,"attempts":0,"progress_summary":None,"status_checked_at":None,"recovery_of":handoff_id,"recovery_reason":policy["classification"],"match_score":score}
    def apply(current):
        source=next((x for x in current.get("handoffs") or [] if str(x.get("id"))==str(handoff_id)),None)
        if not source or source.get("recovery_handoff_id"):return
        source["recovery_handoff_id"]=new_id;source["recovery_action"]="reassigned";current.setdefault("handoffs",[]).append(replacement)
        if agent["id"] not in current.setdefault("agent_ids",[]):current["agent_ids"].append(agent["id"])
        if agent["name"] not in current.setdefault("agent_names",[]):current["agent_names"].append(agent["name"])
        current["status"]="working";current["finished_at"]=None;current["completion_notified_at"]=None;current["replan_count"]=int(current.get("replan_count") or 0)+1;current.setdefault("recovery_history",[]).append({"failed_handoff_id":handoff_id,"replacement_handoff_id":new_id,"from_agent":failed.get("to_agent_name"),"to_agent":agent["name"],"classification":policy["classification"],"at":now})
    updated=team._mutate(job_id,apply) or get_team_job(job_id) or job;created=next((x for x in updated.get("handoffs") or [] if str(x.get("id"))==new_id),None)
    if not created:return {"action":"already_replanned","handoff_id":failed.get("recovery_handoff_id")}
    return {"action":"reassigned","automatic":True,"classification":policy["classification"],"handoff":created,"agent":agent,"score":score}
def finalize_recovery(job_id:str,failed_handoff_id:str,replacement_handoff_id:str)->dict[str,Any]|None:
    from agentie.core import team_orchestrator as team
    def apply(job):
        failed=next((x for x in job.get("handoffs") or [] if str(x.get("id"))==str(failed_handoff_id)),None);replacement=next((x for x in job.get("handoffs") or [] if str(x.get("id"))==str(replacement_handoff_id)),None)
        if not failed or not replacement:return
        if replacement.get("status")=="completed":failed["status"]="recovered";failed["progress_summary"]=f"Recovered by {replacement.get('to_agent_name')}.";failed["recovered_by_handoff_id"]=replacement_handoff_id
        active=[x for x in job.get("handoffs") or [] if x.get("status") in {"queued","working"}];unresolved=[x for x in job.get("handoffs") or [] if x.get("status")=="failed"]
        if active:job["status"]="working"
        elif unresolved:job["status"]="partial" if any(x.get("status") in {"completed","recovered"} for x in job.get("handoffs") or []) else "failed"
        else:job["status"]="completed";job["finished_at"]=team._now()
        outputs=[f"{x['to_agent_name']}:\n{x['result']}" for x in job.get("handoffs") or [] if x.get("status")=="completed" and x.get("result")];job["final_output"]="\n\n---\n\n".join(outputs) if outputs else job.get("final_output")
    return team._mutate(job_id,apply)
def recovery_note(job_id:str)->dict[str,Any]:
    job=get_team_job(job_id)
    if not job:raise ValueError("Team job was not found.")
    lines=[f"Status: {job.get('status')}",f"Replans: {int(job.get('replan_count') or 0)}"]
    for row in job.get("recovery_history") or []:lines.append(f"- {row.get('from_agent')} → {row.get('to_agent')} · {row.get('classification')}")
    failed=[x for x in job.get("handoffs") or [] if x.get("status")=="failed" and not x.get("recovery_handoff_id")]
    for h in failed:
        p=recovery_policy(str(h.get("error") or ""),int(h.get("attempts") or 1));lines.append(f"- {h.get('to_agent_name')}: {p['action']} · {p['classification']}")
    return {"type":"note","title":f"Recovery · {job_id}","content":"\n".join(lines)}
def route_recovery_command(message:str)->dict[str,Any]|None:
    text=" ".join(str(message or "").strip().split());m=re.match(r"^(?:show|inspect|check)\s+(?:failure\s+)?recovery\s+(?:for\s+)?(?:team job\s+)?(team_[a-z0-9]+)$",text,re.I)
    if not m:return None
    try:card=recovery_note(m.group(1))
    except ValueError as exc:return {"message":str(exc),"card":None}
    return {"message":f"Here is the recovery state for {m.group(1)}.","card":card}
