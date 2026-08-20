from __future__ import annotations

import asyncio
import json
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from agentie.core.agent_registry import get_agent, list_agents

WORKSPACE=Path.cwd()/"workspace"
TEAM_FILE=WORKSPACE/"team_jobs.json"
_LOCK=threading.Lock()
_RUNNING:dict[str,threading.Thread]={}


def _now()->str:return datetime.now().astimezone().isoformat(timespec="seconds")
def _load()->list[dict[str,Any]]:
    try:
        value=json.loads(TEAM_FILE.read_text(encoding="utf-8")) if TEAM_FILE.exists() else []
        return value if isinstance(value,list) else []
    except Exception:return []
def _save(items:list[dict[str,Any]])->None:
    TEAM_FILE.parent.mkdir(parents=True,exist_ok=True);TEAM_FILE.write_text(json.dumps(items,indent=2,ensure_ascii=False),encoding="utf-8")
def _mutate(job_id:str,fn)->dict[str,Any]|None:
    with _LOCK:
        items=_load();job=next((x for x in items if x.get("id")==job_id),None)
        if not job:return None
        fn(job);job["updated_at"]=_now();_save(items);return dict(job)
def get_team_job(job_id:str)->dict[str,Any]|None:
    with _LOCK:return next((dict(x) for x in _load() if x.get("id")==job_id),None)
def list_team_jobs(limit:int=20)->list[dict[str,Any]]:
    with _LOCK:return [dict(x) for x in reversed(_load()[-max(1,limit):])]

def _resolve_names(raw:str)->list[dict[str,Any]]:
    names=[x.strip(' .?!\"“”') for x in re.split(r"\s*,\s*|\s+and\s+",raw,flags=re.I) if x.strip()]
    found=[]
    for name in names:
        agent=get_agent(name)
        if not agent:raise ValueError(f"Agent {name} was not found.")
        if all(x["id"]!=agent["id"] for x in found):found.append(agent)
    return found

def create_team_job(task:str,agents:list[dict[str,Any]],requested_by:str="user")->dict[str,Any]:
    if not task.strip():raise ValueError("A team task is required.")
    if not agents:raise ValueError("At least one agent is required.")
    jid="team_"+uuid.uuid4().hex[:10];now=_now()
    handoffs=[{"id":"ho_"+uuid.uuid4().hex[:8],"from":requested_by,"to_agent_id":a["id"],"to_agent_name":a["name"],"task":task.strip(),"context":{"task":task.strip()},"status":"queued","result":None,"error":None} for a in agents]
    job={"id":jid,"task":task.strip(),"status":"queued","requested_by":requested_by,"agent_ids":[a["id"] for a in agents],"agent_names":[a["name"] for a in agents],"handoffs":handoffs,"created_at":now,"updated_at":now,"final_output":None}
    with _LOCK:
        items=_load();items.append(job);_save(items)
    return job

async def _worker(job_id:str,handoff:dict[str,Any])->tuple[str,str|None,str|None]:
    from agentie.core.runner import run_agent
    agent=get_agent(str(handoff["to_agent_id"]))
    if not agent:return handoff["id"],None,"Agent no longer exists."
    def start(job):
        for h in job["handoffs"]:
            if h["id"]==handoff["id"]:h["status"]="working";h["started_at"]=_now()
    _mutate(job_id,start)
    prompt=(f"You are {agent['name']}, the {agent['role']} agent. "
            f"Your purpose is: {agent.get('purpose') or 'complete work within your specialty'}.\n\n"
            "This is a bounded handoff from another Agentie agent. Work only on the task and return a useful result. "
            "Do not assume access to the sender's private chat or memory.\n\nTASK:\n"+str(handoff["task"]))
    session=f"{agent['session_prefix']}handoff:{job_id}"
    try:
        output=await run_agent(prompt,str(agent.get("base") or "general"),session)
        return handoff["id"],output,None
    except Exception as exc:return handoff["id"],None,str(exc)

async def _execute(job_id:str)->None:
    job=get_team_job(job_id)
    if not job:return
    _mutate(job_id,lambda j:j.update(status="working",started_at=_now()))
    results=await asyncio.gather(*[_worker(job_id,h) for h in job["handoffs"]])
    by_id={hid:(out,err) for hid,out,err in results}
    def finish(j):
        outputs=[];failed=0
        for h in j["handoffs"]:
            out,err=by_id.get(h["id"],(None,"No result"));h["result"]=out;h["error"]=err;h["finished_at"]=_now();h["status"]="failed" if err else "completed"
            if err:failed+=1
            elif out:outputs.append(f"{h['to_agent_name']}:\n{out}")
        j["status"]="failed" if failed==len(j["handoffs"]) else "completed";j["finished_at"]=_now();j["final_output"]="\n\n---\n\n".join(outputs) if outputs else None
    _mutate(job_id,finish)

def _thread_run(job_id:str)->None:
    try:asyncio.run(_execute(job_id))
    finally:_RUNNING.pop(job_id,None)
def start_team_job(job_id:str)->None:
    if job_id in _RUNNING and _RUNNING[job_id].is_alive():return
    thread=threading.Thread(target=_thread_run,args=(job_id,),daemon=True,name=f"agentie-{job_id}");_RUNNING[job_id]=thread;thread.start()

def team_job_card(job:dict[str,Any])->dict[str,Any]:
    return {"type":"team_job","id":job["id"],"task":job["task"],"status":job["status"],"agents":job.get("agent_names",[]),"handoffs":[{"id":h["id"],"agent":h["to_agent_name"],"status":h["status"],"error":h.get("error")} for h in job.get("handoffs",[])],"final_output":job.get("final_output")}

def route_team_command(message:str)->dict[str,Any]|None:
    text=" ".join(message.strip().split());lower=text.lower().strip(" .?!")
    if lower in {"show team jobs","list team jobs","show handoffs","list handoffs","show delegations"}:
        items=list_team_jobs();return {"message":f"There are {len(items)} team job(s).","card":{"type":"team_jobs","items":[team_job_card(x) for x in items]}}
    m=re.match(r"^(?:show|check|inspect)\s+(?:team job|handoff|delegation)\s+([a-z0-9_]+)[.!?]?$",text,re.I)
    if m:
        job=get_team_job(m.group(1));return {"message":"Team job not found.","card":None} if not job else {"message":f"Team job {job['id']} is {job['status']}.","card":team_job_card(job)}
    together=re.match(r"^(?:have|ask|tell)\s+(.+?)\s+(?:to\s+)?work\s+together\s+(?:on|to)\s+(.+?)[.!?]?$",text,re.I)
    if together:
        try:agents=_resolve_names(together.group(1))
        except ValueError as exc:return {"message":str(exc),"card":None}
        job=create_team_job(together.group(2),agents);start_team_job(job["id"]);return {"message":f"Started team job {job['id']} with {', '.join(job['agent_names'])} working simultaneously.","card":team_job_card(job)}
    delegate=re.match(r"^(?:delegate|hand off|handoff)\s+(.+?)\s+to\s+(.+?)[.!?]?$",text,re.I)
    if delegate:
        try:agents=_resolve_names(delegate.group(2))
        except ValueError as exc:return {"message":str(exc),"card":None}
        job=create_team_job(delegate.group(1),agents);start_team_job(job["id"]);return {"message":f"Delegated the task to {', '.join(job['agent_names'])} as team job {job['id']}.","card":team_job_card(job)}
    return None
