from __future__ import annotations

import asyncio
import json
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from agentie.core.agent_registry import get_agent, list_agents
from agentie.core.result_memory import remember_global_result

WORKSPACE=Path.cwd()/"workspace"
TEAM_FILE=WORKSPACE/"team_jobs.json"
_LOCK=threading.Lock()
_RUNNING:dict[str,threading.Thread]={}


def _now()->str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _load()->list[dict[str,Any]]:
    try:
        value=json.loads(TEAM_FILE.read_text(encoding="utf-8")) if TEAM_FILE.exists() else []
        return value if isinstance(value,list) else []
    except Exception:
        return []


def _save(items:list[dict[str,Any]])->None:
    TEAM_FILE.parent.mkdir(parents=True,exist_ok=True)
    TEAM_FILE.write_text(json.dumps(items,indent=2,ensure_ascii=False),encoding="utf-8")


def _mutate(job_id:str,fn)->dict[str,Any]|None:
    with _LOCK:
        items=_load();job=next((x for x in items if x.get("id")==job_id),None)
        if not job:return None
        fn(job);job["updated_at"]=_now();_save(items);return dict(job)


def get_team_job(job_id:str)->dict[str,Any]|None:
    with _LOCK:return next((dict(x) for x in _load() if x.get("id")==job_id),None)


def list_team_jobs(limit:int=20)->list[dict[str,Any]]:
    with _LOCK:return [dict(x) for x in reversed(_load()[-max(1,limit):])]


def _role_words(value:str)->set[str]:
    stop={"agent","the","my","a","an","of","for","and","to"}
    return {x for x in re.findall(r"[a-z0-9]+",str(value).casefold()) if x not in stop and len(x)>1}


def _similar_agents(missing_name:str,limit:int=3)->list[dict[str,Any]]:
    wanted=_role_words(missing_name);scored=[]
    for agent in list_agents():
        hay=_role_words(f"{agent.get('name','')} {agent.get('role','')} {agent.get('purpose','')} {agent.get('base','')}")
        score=len(wanted&hay)
        if str(agent.get("name","")).casefold() in str(missing_name).casefold() or str(missing_name).casefold() in str(agent.get("role","")).casefold():score+=2
        if score:scored.append((score,agent))
    return [a for _,a in sorted(scored,key=lambda x:(-x[0],x[1]["name"].casefold()))[:limit]]


def _missing_agent_choice(name:str,task:str,requested_agents:list[str]|None=None)->dict[str,Any]:
    similar=_similar_agents(name)
    options=[{"action":"create_agent","label":f"Create {name}","agent_name":name}]
    options.extend({"action":"use_agent","label":f"Give it to {a['name']}","agent_id":a["id"],"agent_name":a["name"],"role":a["role"]} for a in similar)
    return {"message":f"Agent {name} was not found. Do you want to create it or give this task to a similar existing agent?","card":{"type":"agent_choice","missing_agent":name,"task":task,"requested_agents":requested_agents or [name],"options":options}}


def _resolve_names(raw:str)->tuple[list[dict[str,Any]],str|None]:
    names=[x.strip(' .?!\"“”') for x in re.split(r"\s*,\s*|\s+and\s+",raw,flags=re.I) if x.strip()];found=[]
    for name in names:
        agent=get_agent(name)
        if not agent:return found,name
        if all(x["id"]!=agent["id"] for x in found):found.append(agent)
    return found,None


def create_team_job(task:str,agents:list[dict[str,Any]],requested_by:str="user")->dict[str,Any]:
    if not task.strip():raise ValueError("A team task is required.")
    if not agents:raise ValueError("At least one agent is required.")
    jid="team_"+uuid.uuid4().hex[:10];now=_now()
    handoffs=[{
        "id":"ho_"+uuid.uuid4().hex[:8],"from":requested_by,"to_agent_id":a["id"],"to_agent_name":a["name"],
        "task":task.strip(),"context":{"task":task.strip()},"status":"queued","result":None,"error":None,"attempts":0,
        "progress_summary":None,"status_checked_at":None,
    } for a in agents]
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
            if h["id"]==handoff["id"]:
                h["status"]="working";h["started_at"]=_now();h["attempts"]=int(h.get("attempts",0))+1;h["error"]=None
                h["progress_summary"]=f"Working on {h.get('task') or job.get('task')}.";h["status_checked_at"]=_now()
    _mutate(job_id,start)
    prompt=(f"You are {agent['name']}, the {agent['role']} agent. Your purpose is: {agent.get('purpose') or 'complete work within your specialty'}.\n\n"
            "This is a bounded handoff from another Agentie agent. Work only on the task and return a useful result. Do not assume access to the sender's private chat or memory. Prefer your available local/Python/tools before provider-dependent work when they can complete the task.\n\nTASK:\n"+str(handoff["task"]))
    session=f"{agent['session_prefix']}handoff:{job_id}"
    try:return handoff["id"],await run_agent(prompt,str(agent.get("base") or "general"),session),None
    except Exception as exc:return handoff["id"],None,str(exc)


def _compact(value:str,max_chars:int=260)->str:
    text=re.sub(r"\s+"," ",str(value or "")).strip()
    return text if len(text)<=max_chars else text[:max_chars-1].rstrip()+"…"


def _fallback_status(job:dict[str,Any],handoff:dict[str,Any])->str:
    status=str(handoff.get("status") or "queued")
    if status=="completed":return _compact(str(handoff.get("result") or "Completed the assigned part."))
    if status=="failed":return _compact(f"Failed: {handoff.get('error') or 'the assigned work could not be completed.'}")
    if status=="working":return f"Still working on {job.get('task') or handoff.get('task')}; no completed result has been returned yet."
    return f"Queued for {job.get('task') or handoff.get('task')} and waiting to start."


async def _ask_worker_status(job:dict[str,Any],handoff:dict[str,Any])->tuple[str,str]:
    """Ask an active worker for a tiny update without interrupting its work session."""
    fallback=_fallback_status(job,handoff);status=str(handoff.get("status") or "queued")
    if status not in {"queued","working"}:return handoff["id"],fallback
    agent=get_agent(str(handoff.get("to_agent_id") or ""))
    if not agent:return handoff["id"],fallback
    from agentie.core.runner import run_agent
    prompt=(f"Status check only. You are {agent['name']} and you are assigned to team job {job['id']}.\n"
            f"Task: {job.get('task') or handoff.get('task')}\nBackend state: {status}.\n"
            "Give a truthful progress update in one or two short sentences, maximum 35 words. Do not restart the task, do not produce the deliverable, and do not claim completed work unless the backend state says completed. If you cannot verify partial progress, say you are still working and no completed result is available yet.")
    try:
        value=await asyncio.wait_for(run_agent(prompt,str(agent.get("base") or "general"),f"{agent['session_prefix']}status:{job['id']}"),timeout=18)
        summary=_compact(str(value or ""),320)
        return handoff["id"],summary or fallback
    except Exception:
        return handoff["id"],fallback


async def _collect_worker_status(job:dict[str,Any])->dict[str,str]:
    pairs=await asyncio.gather(*[_ask_worker_status(job,h) for h in job.get("handoffs",[])])
    return {hid:summary for hid,summary in pairs}


def request_team_status(job_id:str)->dict[str,Any]:
    job=get_team_job(job_id)
    if not job:raise ValueError("Team job was not found.")
    with ThreadPoolExecutor(max_workers=1,thread_name_prefix="agentie-team-status") as pool:
        summaries=pool.submit(lambda:asyncio.run(_collect_worker_status(job))).result()
    checked=_now()
    def apply(j):
        for h in j.get("handoffs",[]):
            h["progress_summary"]=summaries.get(h["id"]) or _fallback_status(j,h);h["status_checked_at"]=checked
        j["status_checked_at"]=checked
    updated=_mutate(job_id,apply) or job
    remember_global_result("",team_job_card(updated))
    return updated


def _latest_job_for_status()->dict[str,Any]|None:
    jobs=list_team_jobs(30)
    return next((j for j in jobs if j.get("status") in {"queued","working"}),jobs[0] if jobs else None)


def _looks_like_status_request(lower:str)->bool:
    if re.search(r"\bteam_[a-z0-9]+\b",lower) and re.search(r"\b(status|state|progress|update|doing|going)\b",lower):return True
    patterns=[
        r"\b(?:state|status|progress)\s+(?:of|on)\s+(?:that|this|the)\s+(?:task|job|team job)\b",
        r"\bhow\s+(?:is|are)\s+(?:that|this|the|they|the agents?|those agents?)\b.*\b(?:task|job|doing|going|progress)\b",
        r"\bhow\s+are\s+they\s+doing\b",
        r"\b(?:give|show|tell)\s+me\s+(?:a\s+)?(?:quick\s+|small\s+|brief\s+)?update\s+(?:on|about)\s+(?:that|this|the)\s+(?:task|job|team job)\b",
        r"\bwhat\s+are\s+(?:the\s+)?agents?\s+doing\b",
    ]
    return any(re.search(p,lower) for p in patterns)


def team_job_card(job:dict[str,Any])->dict[str,Any]:
    return {
        "type":"team_job","id":job["id"],"task":job["task"],"status":job["status"],"agents":job.get("agent_names",[]),
        "handoffs":[{"id":h["id"],"agent":h["to_agent_name"],"status":h["status"],"error":h.get("error"),"attempts":h.get("attempts",0),"summary":h.get("progress_summary"),"status_checked_at":h.get("status_checked_at")} for h in job.get("handoffs",[])],
        "final_output":job.get("final_output"),"created_at":job.get("created_at"),"started_at":job.get("started_at"),"finished_at":job.get("finished_at"),"updated_at":job.get("updated_at"),"status_checked_at":job.get("status_checked_at"),
    }


def _status_message(job:dict[str,Any])->str:
    lines=[f"Team task is {job.get('status','unknown')}." ]
    for h in job.get("handoffs",[]):
        summary=str(h.get("progress_summary") or _fallback_status(job,h)).strip()
        lines.append(f"{h.get('to_agent_name') or 'Agent'}: {summary}")
    return "\n".join(lines)


def _finish_job(job_id:str,results:list[tuple[str,str|None,str|None]],only_ids:set[str]|None=None)->None:
    by_id={hid:(out,err) for hid,out,err in results}
    def finish(j):
        for h in j["handoffs"]:
            if only_ids is not None and h["id"] not in only_ids:continue
            out,err=by_id.get(h["id"],(None,"No result"));h["result"]=out;h["error"]=err;h["finished_at"]=_now();h["status"]="failed" if err else "completed";h["progress_summary"]=_fallback_status(j,h);h["status_checked_at"]=_now()
        completed=[h for h in j["handoffs"] if h.get("status")=="completed"];failed=[h for h in j["handoffs"] if h.get("status")=="failed"];active=[h for h in j["handoffs"] if h.get("status") in {"queued","working"}]
        if active:j["status"]="working"
        elif completed and failed:j["status"]="partial"
        elif completed and len(completed)==len(j["handoffs"]):j["status"]="completed"
        else:j["status"]="failed"
        if not active:j["finished_at"]=_now()
        outputs=[f"{h['to_agent_name']}:\n{h['result']}" for h in j["handoffs"] if h.get("status")=="completed" and h.get("result")]
        j["final_output"]="\n\n---\n\n".join(outputs) if outputs else None
    updated=_mutate(job_id,finish)
    if updated:remember_global_result("",team_job_card(updated))


async def _execute(job_id:str,only_ids:set[str]|None=None)->None:
    job=get_team_job(job_id)
    if not job:return
    targets=[h for h in job["handoffs"] if only_ids is None or h["id"] in only_ids]
    if not targets:return
    _mutate(job_id,lambda j:j.update(status="working",started_at=j.get("started_at") or _now()))
    results=await asyncio.gather(*[_worker(job_id,h) for h in targets])
    _finish_job(job_id,results,only_ids)


def _thread_run(job_id:str,only_ids:set[str]|None=None)->None:
    try:asyncio.run(_execute(job_id,only_ids))
    finally:_RUNNING.pop(job_id,None)


def start_team_job(job_id:str,only_ids:set[str]|None=None)->None:
    if job_id in _RUNNING and _RUNNING[job_id].is_alive():return
    thread=threading.Thread(target=_thread_run,args=(job_id,only_ids),daemon=True,name=f"agentie-{job_id}")
    _RUNNING[job_id]=thread;thread.start()


def retry_team_worker(job_id:str,agent_name:str)->dict[str,Any]:
    job=get_team_job(job_id)
    if not job:raise ValueError("Team job was not found.")
    handoff=next((h for h in job["handoffs"] if str(h.get("to_agent_name","")).casefold()==agent_name.casefold()),None)
    if not handoff:raise ValueError(f"Agent {agent_name} is not part of this team job.")
    if handoff.get("status")!="failed":raise ValueError(f"{handoff['to_agent_name']} is not failed and does not need a retry.")
    hid=handoff["id"]
    _mutate(job_id,lambda j:[h.update(status="queued",error=None,progress_summary=None,status_checked_at=None) for h in j["handoffs"] if h["id"]==hid])
    start_team_job(job_id,{hid})
    return get_team_job(job_id) or job


def route_team_command(message:str)->dict[str,Any]|None:
    text=" ".join(message.strip().split());lower=text.lower().strip(" .?!")
    if _looks_like_status_request(lower):
        id_match=re.search(r"\b(team_[a-z0-9]+)\b",lower)
        job=get_team_job(id_match.group(1)) if id_match else _latest_job_for_status()
        if not job:return None
        try:job=request_team_status(job["id"])
        except ValueError:return {"message":"Team job not found.","card":None}
        return {"message":_status_message(job),"card":team_job_card(job)}
    if lower in {"show team jobs","list team jobs","show handoffs","list handoffs","show delegations"}:
        items=list_team_jobs();return {"message":f"There are {len(items)} team job(s).","card":{"type":"team_jobs","items":[team_job_card(x) for x in items]}}
    m=re.match(r"^(?:show|check|inspect)\s+(?:team job|handoff|delegation)\s+([a-z0-9_]+)[.!?]?$",text,re.I)
    if m:
        job=get_team_job(m.group(1));return {"message":"Team job not found.","card":None} if not job else {"message":f"Team job {job['id']} is {job['status']}.","card":team_job_card(job)}
    retry=re.match(r"^(?:retry|try again)\s+(.+?)\s+(?:on|for|in)\s+(?:team job\s+)?([a-z0-9_]+)[.!?]?$",text,re.I)
    if retry:
        try:job=retry_team_worker(retry.group(2),retry.group(1).strip())
        except ValueError as exc:return {"message":str(exc),"card":None}
        return {"message":f"Retrying {retry.group(1).strip()} on team job {job['id']}.","card":team_job_card(job)}
    together=re.match(r"^(?:have|ask|tell)\s+(.+?)\s+(?:to\s+)?work\s+together\s+(?:on|to)\s+(.+?)[.!?]?$",text,re.I)
    if together:
        raw_names=together.group(1);task=together.group(2);agents,missing=_resolve_names(raw_names)
        if missing:return _missing_agent_choice(missing,task,[x.strip() for x in re.split(r"\s*,\s*|\s+and\s+",raw_names,flags=re.I)])
        job=create_team_job(task,agents);start_team_job(job["id"]);card=team_job_card(job);remember_global_result("",card)
        return {"message":f"Started team job {job['id']} with {', '.join(job['agent_names'])} working simultaneously.","card":card}
    delegate=re.match(r"^(?:delegate|hand off|handoff)\s+(.+?)\s+to\s+(.+?)[.!?]?$",text,re.I)
    if delegate:
        task=delegate.group(1);raw_names=delegate.group(2);agents,missing=_resolve_names(raw_names)
        if missing:return _missing_agent_choice(missing,task,[x.strip() for x in re.split(r"\s*,\s*|\s+and\s+",raw_names,flags=re.I)])
        job=create_team_job(task,agents);start_team_job(job["id"]);card=team_job_card(job);remember_global_result("",card)
        return {"message":f"Delegated the task to {', '.join(job['agent_names'])} as team job {job['id']}.","card":card}
    return None
