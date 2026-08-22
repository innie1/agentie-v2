from __future__ import annotations

import re
import threading
import time
from typing import Any

from agentie.core.agent_matching import best_agent,match_score
from agentie.core.agent_registry import get_agent
from agentie.core.memory_store import set_context
from agentie.core.team_orchestrator import create_team_job,get_team_job,start_team_job

_CONTROLLERS:dict[str,threading.Thread]={};_LOCK=threading.Lock()
_ACTION=re.compile(r"^(?:research|find|compare|investigate|analyze|analyse|write|draft|create|make|build|implement|develop|code|test|verify|review|check|design|plan|organize|organise|contact|email|send|prepare|calculate|update|publish|post|summarize|summarise)\b",re.I)
_ARTIFACT_RE=re.compile(r"\b(?:pdf|docx|xlsx|pptx|powerpoint|slide\s*deck|slides?|spreadsheet|excel|word\s+document|csv)\b",re.I)
_ARTIFACT_CREATE_RE=re.compile(r"\b(?:create|make|generate|write|prepare|build|export|produce|turn|convert)\b",re.I)

def _active_manager(session_id:str|None)->dict[str,Any]|None:
    m=re.match(r"^agent:(agt_[a-z0-9]+):",str(session_id or ""),re.I)
    if not m:return None
    agent=get_agent(m.group(1));return agent if agent and bool((agent.get("permissions") or {}).get("delegate")) else None

def _advice_only(goal:str)->bool:
    low=" ".join(str(goal or "").casefold().split());advice=bool(re.search(r"\b(?:what do you think|your opinion|should we|should i|would you recommend|do you recommend|which .* better|best option|good idea|bad idea|worth it|what should .* prioritize)\b",low));proceed=bool(re.search(r"\b(?:go ahead|do it|proceed|start now|execute|make it happen|carry it out)\b",low));return advice and not proceed

def _artifact_compound_request(goal:str)->bool:
    text=" ".join(str(goal or "").strip().split())
    if not (_ARTIFACT_RE.search(text) and _ARTIFACT_CREATE_RE.search(text)):return False
    return bool(re.search(r"\b(?:then|after|and then|after that)\b|;",text,re.I))
def _split_goal(goal:str)->list[str]:
    clean=" ".join(str(goal or "").strip().split())
    if not clean:return []
    clauses=[x.strip(" .") for x in re.split(r"\s*(?:;|\bthen\b|\band then\b|\bafter that\b)\s*",clean,flags=re.I) if x.strip(" .")]
    if len(clauses)>1:return clauses[:8]
    comma=[x.strip(" .") for x in re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+",clean,flags=re.I) if x.strip(" .")];actionable=[x for x in comma if _ACTION.search(x)];return actionable[:8] if len(actionable)>=2 else []
def build_autopilot_plan(goal:str,manager:dict[str,Any])->dict[str,Any]|None:
    if not bool((manager.get("permissions") or {}).get("delegate")) or _advice_only(goal):return None
    if _artifact_compound_request(goal):return None
    clauses=_split_goal(goal)
    if len(clauses)<2:return None
    steps=[]
    for index,clause in enumerate(clauses,1):
        agent=best_agent(clause,exclude_id=str(manager.get("id")),min_score=.16)
        if not agent:continue
        score=match_score(clause,agent);steps.append({"phase":f"step_{index}","label":clause[:80],"agent":agent,"task":clause,"score":score})
    if len(steps)<2:return None
    return {"goal":goal.strip(),"manager":manager,"steps":steps,"missing":[],"sequential":bool(re.search(r"\b(?:then|after that|and then)\b",goal,re.I) or ";" in goal)}
def _configure(job_id:str,plan:dict[str,Any])->dict[str,Any]:
    from agentie.core import team_orchestrator as team
    steps=list(plan["steps"]);by_agent={}
    for step in steps:by_agent.setdefault(str(step["agent"]["id"]),[]).append(step)
    def apply(job):
        job["autopilot"]=True;job["autopilot_manager_id"]=plan["manager"]["id"];job["autopilot_manager_name"]=plan["manager"]["name"];job["autopilot_goal"]=plan["goal"];job["autopilot_kind"]="configured_agent_plan";job["autopilot_sequential"]=bool(plan.get("sequential"));job["autopilot_recovery_enabled"]=True;job["autopilot_recovery_finalized"]=False;job.setdefault("replan_count",0);job.setdefault("recovery_history",[]);ordered=[]
        for handoff in job.get("handoffs",[]):
            owned=by_agent.get(str(handoff.get("to_agent_id")),[])
            if not owned:continue
            task="\n".join(f"{i+1}. {x['task']}" for i,x in enumerate(owned));handoff["task"]=task;handoff.setdefault("context",{})["task"]=task;handoff["context"]["autopilot_goal"]=plan["goal"];handoff["match_scores"]=[x["score"] for x in owned];ordered.append(handoff["id"])
        if job["autopilot_sequential"]:
            for index,hid in enumerate(ordered):
                handoff=next((x for x in job.get("handoffs",[]) if x.get("id")==hid),None)
                if handoff is not None:handoff["depends_on"]=[] if index==0 else [ordered[index-1]]
        job["autopilot_order"]=ordered
    return team._mutate(job_id,apply) or get_team_job(job_id) or {}
_configure_team_job=_configure

def _inject_dependency(job_id:str,next_hid:str,previous:dict[str,Any],goal:str)->dict[str,Any]|None:
    from agentie.core import team_orchestrator as team
    result=str(previous.get("result") or "").strip()
    if not result:return get_team_job(job_id)
    previous_name=str(previous.get("to_agent_name") or "Previous agent");previous_id=str(previous.get("id") or "");brief=(f"Dependency from {previous_name}. Use only this dependency result for the next assigned step; only this dependency is shared, not the previous agent's private memory or conversation.\n\nShared goal: {goal}\n\nDependency result:\n{result[:12000]}")
    def apply(job):
        target=next((x for x in job.get("handoffs",[]) if str(x.get("id"))==str(next_hid)),None)
        if not target:return
        context=target.setdefault("context",{});context["scoped_brief"]=brief;context["dependency_handoff_id"]=previous_id;context["dependency_agent_name"]=previous_name
    return team._mutate(job_id,apply) or get_team_job(job_id)
def _wait_terminal(job_id,hid):
    while True:
        time.sleep(.1);job=get_team_job(job_id)
        if not job:return None
        h=next((x for x in job.get("handoffs",[]) if x.get("id")==hid),None)
        if not h:return None
        if h.get("status") in {"completed","failed","cancelled","recovered"}:return h

def _recover(job_id:str,failed:dict[str,Any])->dict[str,Any]|None:
    """Bounded multi-hop recovery. Approval/missing-input failures never bypass the user."""
    from agentie.core.failure_recovery import MAX_REPLAN_HOPS,finalize_recovery_chain,replan_failed_handoff
    current=failed
    for _ in range(MAX_REPLAN_HOPS):
        decision=replan_failed_handoff(job_id,str(current.get("id") or ""))
        if decision.get("action")!="reassigned":return None
        replacement=decision.get("handoff") or {};hid=str(replacement.get("id") or "")
        if not hid:return None
        start_team_job(job_id,{hid});done=_wait_terminal(job_id,hid)
        if not done:return None
        if done.get("status")=="completed":finalize_recovery_chain(job_id,hid);return done
        if done.get("status")!="failed":return None
        current=done
    return None

def _finish_controller(job_id:str)->None:
    """Release delayed final reporting only after all recovery decisions finish."""
    from agentie.core import team_orchestrator as team
    job=get_team_job(job_id)
    if not job:return
    # A failed sequential dependency can leave later planned handoffs queued. At
    # controller exit those are blocked work, not live work. Mark them explicitly
    # so the job cannot remain 'working' forever.
    if str(job.get("status") or "")=="working":
        running=[x for x in job.get("handoffs") or [] if x.get("status")=="working"]
        queued=[x for x in job.get("handoffs") or [] if x.get("status")=="queued"]
        if queued and not running:
            def block(current):
                for h in current.get("handoffs") or []:
                    if h.get("status")=="queued":h["status"]="cancelled";h["error"]="Blocked by an unresolved dependency or exhausted recovery path.";h["progress_summary"]="Not run because an earlier dependency could not be recovered.";h["finished_at"]=team._now()
                done=[h for h in current.get("handoffs") or [] if h.get("status") in {"completed","recovered"}];bad=[h for h in current.get("handoffs") or [] if h.get("status") in {"failed","cancelled"}]
                current["status"]="partial" if done and bad else "failed" if bad else "completed";current["finished_at"]=team._now()
            job=team._mutate(job_id,block) or get_team_job(job_id) or job
    status=str(job.get("status") or "")
    if status in {"failed","partial","cancelled"}:
        team.publish_team_terminal(job_id);return
    def mark(current):current["autopilot_recovery_finalized"]=True
    team._mutate(job_id,mark)

def _controller(job_id:str)->None:
    try:
        job=get_team_job(job_id)
        if not job:return
        order=list(job.get("autopilot_order") or []);goal=str(job.get("autopilot_goal") or job.get("task") or "")
        if not job.get("autopilot_sequential"):
            start_team_job(job_id)
            for hid in order:
                done=_wait_terminal(job_id,hid)
                if done and done.get("status")=="failed":_recover(job_id,done)
            _finish_controller(job_id);return
        for index,hid in enumerate(order):
            while True:
                start_team_job(job_id,{hid});time.sleep(.06);current=get_team_job(job_id);h=next((x for x in (current or {}).get("handoffs",[]) if x.get("id")==hid),None)
                if not h or h.get("status")!="queued":break
            done=_wait_terminal(job_id,hid)
            if done and done.get("status")=="failed":done=_recover(job_id,done)
            if not done or done.get("status")!="completed":break
            if index+1<len(order):_inject_dependency(job_id,order[index+1],done,goal)
        _finish_controller(job_id)
    finally:
        with _LOCK:_CONTROLLERS.pop(job_id,None)
def start_autopilot_job(plan:dict[str,Any],session_id:str|None=None)->dict[str,Any]:
    unique=[];seen=set()
    for step in plan["steps"]:
        agent=step["agent"]
        if str(agent["id"]) not in seen:seen.add(str(agent["id"]));unique.append(agent)
    job=create_team_job(plan["goal"],unique,requested_by=str(plan["manager"]["id"]));job=_configure(job["id"],plan)
    if session_id:set_context(session_id,"active_team_job_id",job["id"]);set_context(session_id,"active_team_job_task",plan["goal"])
    thread=threading.Thread(target=_controller,args=(job["id"],),daemon=True,name=f"agentie-configured-plan-{job['id']}")
    with _LOCK:_CONTROLLERS[job["id"]]=thread
    thread.start();return get_team_job(job["id"]) or job
def maybe_manager_autopilot(message:str,session_id:str|None)->dict[str,Any]|None:
    manager=_active_manager(session_id)
    if not manager:return None
    text=" ".join(str(message or "").strip().split());lower=text.casefold().strip(" .?!")
    if not text or re.match(r"^(show|list|delete|remove|rename|remember|set|create an agent|make an agent|delegate|handoff|hand off|have |ask |tell |retry|pause|resume|cancel|approve|deny)",lower):return None
    plan=build_autopilot_plan(text,manager)
    if not plan:return None
    job=start_autopilot_job(plan,session_id);owners=[]
    for step in plan["steps"]:
        name=step["agent"]["name"]
        if name not in owners:owners.append(name)
    return {"message":f"{manager['name']} split this into {len(plan['steps'])} configured work item(s) across {', '.join(owners)}. Recoverable worker failures can be re-planned across multiple untried configured owners, while approval and missing-input boundaries still stop for you.","card":{"type":"team_job",**{k:v for k,v in job.items() if k!="handoffs"},"handoffs":[{"id":h["id"],"agent":h["to_agent_name"],"status":h["status"],"summary":h.get("progress_summary"),"error":h.get("error")} for h in job.get("handoffs",[])],"agents":job.get("agent_names",[]),"final_output":job.get("final_output")}}