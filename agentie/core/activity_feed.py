from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from agentie.core.agent_registry import get_agent
from agentie.core.automation_events import recent_events
from agentie.core.observability import recent_traces
from agentie.core.routine_engine import list_routines,list_runs
from agentie.core.team_orchestrator import list_team_jobs
from agentie.core.workflow_skill_runtime import list_skill_runs
from agentie.tools.approval_tools import recent_approvals


def _at(value:Any)->str:return str(value or "")
def _session_agent(session_id:str|None)->str|None:
    m=re.match(r"^agent:(agt_[a-z0-9]+):",str(session_id or ""),re.I);return m.group(1) if m else None
def _name(agent_id:str|None)->str|None:
    a=get_agent(str(agent_id or "")) if agent_id else None;return str(a.get("name")) if a else None
def _sort_key(item:dict[str,Any]):
    raw=str(item.get("at") or "")
    try:return datetime.fromisoformat(raw.replace("Z","+00:00")).timestamp()
    except Exception:return 0.0
def _event_matches_agent(payload:dict[str,Any],agent_id:str)->bool:
    if str(payload.get("agent_id") or "")==str(agent_id):return True
    return str(agent_id) in {str(x) for x in payload.get("agent_ids") or []}

def activity_items(*,agent_id:str|None=None,limit:int=60)->list[dict[str,Any]]:
    """Merge existing authoritative stores; never create a duplicate activity DB."""
    rows=[]
    for trace in recent_traces(None,min(100,max(limit,30))):
        aid=_session_agent(trace.get("session_id"))
        if agent_id and str(aid)!=str(agent_id):continue
        rows.append({"id":"trace:"+str(trace.get("id")),"kind":"trace","title":"Agent request","status":trace.get("status"),"at":trace.get("finished_at") or trace.get("started_at"),"agent_id":aid,"agent_name":_name(aid),"summary":str(trace.get("user_message") or "")[:300],"metadata":{"routed_by":trace.get("routed_by"),"provider_calls":trace.get("provider_calls",0),"tokens":trace.get("total_tokens",0)}})
    for job in list_team_jobs(100):
        ids=[str(x) for x in job.get("agent_ids") or []]
        if agent_id and str(agent_id) not in ids and str(job.get("requested_by"))!=str(agent_id):continue
        rows.append({"id":"team:"+str(job.get("id")),"kind":"collaboration","title":"Agent collaboration","status":job.get("status"),"at":job.get("finished_at") or job.get("updated_at") or job.get("created_at"),"agent_id":str(agent_id) if agent_id else None,"agent_name":_name(agent_id),"summary":str(job.get("task") or "")[:300],"metadata":{"agents":job.get("agent_names") or [],"team_job_id":job.get("id"),"replan_count":job.get("replan_count",0),"recovery_history":job.get("recovery_history") or []}})
    for run in list_skill_runs(agent_id=agent_id,limit=100):
        rows.append({"id":"skill:"+str(run.get("id")),"kind":"skill","title":"Skill · "+str(run.get("skill_name") or "Workflow"),"status":run.get("status"),"at":run.get("finished_at") or run.get("updated_at") or run.get("created_at"),"agent_id":run.get("agent_id"),"agent_name":run.get("agent_name"),"summary":str(run.get("result") or run.get("error") or "")[:300],"metadata":{"skill_id":run.get("skill_id"),"skill_run_id":run.get("id"),"approval_ids":run.get("approval_ids") or []}})
    routine_by_id={str(x.get("id")):x for x in list_routines()}
    for run in list_runs(limit=200):
        routine=routine_by_id.get(str(run.get("routine_id"))) or {};aid=routine.get("owner_agent_id")
        if agent_id and str(aid)!=str(agent_id):continue
        rows.append({"id":"routine:"+str(run.get("id") or f"{run.get('routine_id')}:{run.get('at')}"),"kind":"routine","title":"Routine · "+str(routine.get("name") or run.get("routine_id") or "Routine"),"status":run.get("status"),"at":run.get("at"),"agent_id":aid,"agent_name":routine.get("owner_agent_name") or _name(aid),"summary":str(routine.get("action") or "")[:300],"metadata":{"routine_id":run.get("routine_id"),"job_id":run.get("job_id"),"event_id":run.get("event_id"),"skill_id":run.get("skill_id"),"retried":run.get("retried")}})
    for approval in recent_approvals(agent_id=agent_id,limit=100):
        meta=approval.get("metadata") or {};aid=meta.get("agent_id")
        if agent_id and str(aid)!=str(agent_id):continue
        rows.append({"id":"approval:"+str(approval.get("id")),"kind":"approval","title":"Approval · "+str(meta.get("tool") or meta.get("kind") or "action"),"status":approval.get("status"),"at":approval.get("resolved_at") or approval.get("created_at"),"agent_id":aid,"agent_name":meta.get("agent_name") or _name(aid),"summary":str(approval.get("reason") or approval.get("action") or "")[:300],"metadata":{"approval_id":approval.get("id"),"server":meta.get("server"),"tool":meta.get("tool")}})
    for event in recent_events(200):
        payload=dict(event.get("payload") or {})
        if agent_id and not _event_matches_agent(payload,str(agent_id)):continue
        etype=str(event.get("type") or "event");summary=str(payload.get("message") or payload.get("task") or payload.get("body") or payload.get("name") or "")[:300]
        rows.append({"id":"event:"+str(event.get("id")),"kind":"automation_event","title":"Automation event · "+etype,"status":"delivered" if event.get("closed_at") else "pending","at":event.get("created_at"),"agent_id":payload.get("agent_id"),"agent_name":payload.get("agent_name") or _name(payload.get("agent_id")),"summary":summary,"metadata":{"event_type":etype,"source":event.get("source"),"delivered_routine_ids":event.get("delivered_routine_ids") or [],"team_job_id":payload.get("team_job_id")}})
    unique={str(x["id"]):x for x in rows};items=sorted(unique.values(),key=_sort_key,reverse=True);return items[:max(1,min(int(limit),200))]

def activity_note(*,agent_id:str|None=None,limit:int=40)->dict[str,Any]:
    items=activity_items(agent_id=agent_id,limit=limit);owner=_name(agent_id) if agent_id else None;lines=[]
    for item in items:
        who=f" · {item.get('agent_name')}" if item.get("agent_name") else "";status=str(item.get("status") or "").replace("_"," ");summary=str(item.get("summary") or "").strip();line=f"{item.get('at') or ''} · {item.get('title')}{who} · {status}"
        if summary:line+=f"\n  {summary}"
        lines.append(line)
    if not lines:lines=["No recorded activity yet."]
    return {"type":"note","title":f"Activity timeline · {owner}" if owner else "Activity timeline","content":"\n\n".join(lines),"activity_items":items,"agent_id":agent_id}
