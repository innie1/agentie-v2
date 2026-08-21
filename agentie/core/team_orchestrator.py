from __future__ import annotations

import asyncio,json,re,threading,uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any
from agentie.core.agent_registry import get_agent,list_agents
from agentie.core.result_memory import remember_global_result
from agentie.core.memory_store import add_message
from agentie.core.project_brain import get_project,project_context,record_handoff,record_worker_result,route_project_command,update_agent_work_status

WORKSPACE=Path.cwd()/"workspace";TEAM_FILE=WORKSPACE/"team_jobs.json";_LOCK=threading.Lock();_RUNNING={}
def _now():return datetime.now().astimezone().isoformat(timespec="seconds")
def _load():
    try:
        v=json.loads(TEAM_FILE.read_text(encoding="utf-8")) if TEAM_FILE.exists() else [];return v if isinstance(v,list) else []
    except Exception:return []
def _save(v):TEAM_FILE.parent.mkdir(parents=True,exist_ok=True);TEAM_FILE.write_text(json.dumps(v,indent=2,ensure_ascii=False),encoding="utf-8")
def _mutate(jid,fn):
    with _LOCK:
        items=_load();j=next((x for x in items if x.get("id")==jid),None)
        if not j:return None
        fn(j);j["updated_at"]=_now();_save(items);return dict(j)
def get_team_job(jid):
    with _LOCK:return next((dict(x) for x in _load() if x.get("id")==jid),None)
def list_team_jobs(limit=20):
    with _LOCK:return [dict(x) for x in reversed(_load()[-max(1,limit):])]
def _role_words(v):return {x for x in re.findall(r"[a-z0-9]+",str(v).casefold()) if x not in {"agent","the","my","a","an","of","for","and","to"} and len(x)>1}
def _similar_agents(name,limit=3):
    wanted=_role_words(name);scored=[]
    for a in list_agents():
        hay=_role_words(f"{a.get('name','')} {a.get('role','')} {a.get('purpose','')} {a.get('base','')}");score=len(wanted&hay)
        if str(a.get("name","")).casefold() in name.casefold() or name.casefold() in str(a.get("role","")).casefold():score+=2
        if score:scored.append((score,a))
    return [a for _,a in sorted(scored,key=lambda x:(-x[0],x[1]["name"].casefold()))[:limit]]
def _missing_agent_choice(name,task,requested_agents=None):
    options=[{"action":"create_agent","label":f"Create {name}","agent_name":name}]+[{"action":"use_agent","label":f"Give it to {a['name']}","agent_id":a["id"],"agent_name":a["name"],"role":a["role"]} for a in _similar_agents(name)]
    return {"message":f"Agent {name} was not found. Do you want to create it or give this task to a similar existing agent?","card":{"type":"agent_choice","missing_agent":name,"task":task,"requested_agents":requested_agents or [name],"options":options}}
def _resolve_names(raw):
    names=[x.strip(' .?!\"“”') for x in re.split(r"\s*,\s*|\s+and\s+",raw,flags=re.I) if x.strip()];found=[]
    for name in names:
        a=get_agent(name)
        if not a:return found,name
        if all(x["id"]!=a["id"] for x in found):found.append(a)
    return found,None

def create_team_job(task,agents,requested_by="user",project_id=None):
    if not str(task).strip():raise ValueError("A team task is required.")
    if not agents:raise ValueError("At least one agent is required.")
    project=get_project(project_id) if project_id else None;jid="team_"+uuid.uuid4().hex[:10];now=_now()
    hs=[]
    for a in agents:
        task_text=str(task).strip()
        if project:
            scoped=project_context(project,a.get("role") or a.get("base"),task_text)
            context={"task":task_text,"project_id":project.get("id"),"scoped_brief":scoped}
        else:
            context={"task":task_text}
        h={"id":"ho_"+uuid.uuid4().hex[:8],"from":requested_by,"to_agent_id":a["id"],"to_agent_name":a["name"],"task":task_text,"context":context,"status":"queued","result":None,"error":None,"attempts":0,"progress_summary":None,"status_checked_at":None};hs.append(h)
    job={"id":jid,"task":str(task).strip(),"status":"queued","requested_by":requested_by,"project_id":project.get("id") if project else None,"agent_ids":[a["id"] for a in agents],"agent_names":[a["name"] for a in agents],"handoffs":hs,"created_at":now,"updated_at":now,"final_output":None}
    with _LOCK:items=_load();items.append(job);_save(items)
    if project:
        for a in agents:record_handoff(project["id"],requested_by,a["name"],task,jid)
    return job

def _mirror(agent,role,content,metadata):
    """Put handoff activity in the specialist's normal chat timeline, not the manager chat."""
    try:add_message(f"{agent['session_prefix']}main",role,content,metadata)
    except Exception:pass
async def _worker(jid,h):
    from agentie.core.runner import run_agent
    a=get_agent(str(h["to_agent_id"]));pid=h.get("context",{}).get("project_id")
    if not a:
        if pid:update_agent_work_status(pid,str(h.get("to_agent_id") or h.get("to_agent_name") or ""),"failed","Agent no longer exists.")
        return h["id"],None,"Agent no longer exists."
    def start(j):
        for x in j["handoffs"]:
            if x["id"]==h["id"]:x.update(status="working",started_at=_now(),attempts=int(x.get("attempts",0))+1,error=None,progress_summary=f"Working on {x.get('task') or j.get('task')}.",status_checked_at=_now())
    _mutate(jid,start)
    if pid:update_agent_work_status(pid,a["id"],"working")
    brief=str(h.get("context",{}).get("scoped_brief") or h["task"])
    visible=f"Project handoff: {h['task']}";_mirror(a,"user",visible,{"routed_by":"project_handoff","team_job_id":jid,"project_id":pid})
    prompt=f"You are {a['name']}, the {a['role']} agent. Work only within your specialty. This is a bounded handoff. Never absorb another worker's private chat. Return a useful deliverable and a concise handoff summary.\n\n{brief}"
    try:
        out=await run_agent(prompt,str(a.get("base") or "general"),f"{a['session_prefix']}handoff:{jid}");_mirror(a,"assistant",out,{"routed_by":"project_handoff_result","team_job_id":jid,"project_id":pid})
        if pid:record_worker_result(pid,a["name"],a.get("role") or a.get("base"),h["task"],out)
        return h["id"],out,None
    except Exception as exc:
        msg=str(exc);_mirror(a,"assistant",f"Handoff failed: {msg}",{"routed_by":"project_handoff_result","team_job_id":jid,"project_id":pid,"failed":True})
        if pid:update_agent_work_status(pid,a["id"],"failed",f"Handoff failed: {msg}")
        return h["id"],None,msg
def _compact(v,n=260):
    t=re.sub(r"\s+"," ",str(v or "")).strip();return t if len(t)<=n else t[:n-1].rstrip()+"…"
def _fallback_status(j,h):
    s=str(h.get("status") or "queued")
    if s=="completed":return _compact(h.get("result") or "Completed the assigned part.")
    if s=="failed":return _compact(f"Failed: {h.get('error') or 'the assigned work could not be completed.'}")
    if s=="working":return f"Still working on {j.get('task') or h.get('task')}; no completed result has been returned yet."
    return f"Queued for {j.get('task') or h.get('task')} and waiting to start."
async def _ask_worker_status(j,h):
    fallback=_fallback_status(j,h);s=str(h.get("status") or "queued")
    if s not in {"queued","working"}:return h["id"],fallback
    a=get_agent(str(h.get("to_agent_id") or ""))
    if not a:return h["id"],fallback
    from agentie.core.runner import run_agent
    p=f"Status check only for team job {j['id']}. Task: {j.get('task')}. Backend state: {s}. Give a truthful 1-2 sentence update, max 35 words. Do not restart work or claim completion unless backend says completed."
    try:v=await asyncio.wait_for(run_agent(p,str(a.get("base") or "general"),f"{a['session_prefix']}status:{j['id']}"),timeout=18);return h["id"],_compact(v,320) or fallback
    except Exception:return h["id"],fallback
async def _collect_worker_status(j):return {hid:s for hid,s in await asyncio.gather(*[_ask_worker_status(j,h) for h in j.get("handoffs",[])])}
def request_team_status(jid):
    j=get_team_job(jid)
    if not j:raise ValueError("Team job was not found.")
    with ThreadPoolExecutor(max_workers=1,thread_name_prefix="agentie-team-status") as pool:summaries=pool.submit(lambda:asyncio.run(_collect_worker_status(j))).result()
    checked=_now()
    def apply(x):
        for h in x.get("handoffs",[]):h["progress_summary"]=summaries.get(h["id"]) or _fallback_status(x,h);h["status_checked_at"]=checked
        x["status_checked_at"]=checked
    u=_mutate(jid,apply) or j;remember_global_result("",team_job_card(u));return u
def _latest_job_for_status():
    jobs=list_team_jobs(30);return next((j for j in jobs if j.get("status") in {"queued","working"}),jobs[0] if jobs else None)
def _looks_like_status_request(l):return bool((re.search(r"\bteam_[a-z0-9]+\b",l) and re.search(r"\b(status|state|progress|update|doing|going)\b",l)) or re.search(r"\b(state|status|progress)\s+(of|on)\s+(that|this|the)\s+(task|job|team job)\b|\bhow are they doing\b|\bwhat are (the )?agents? doing\b|\b(give|show|tell) me (a )?(quick |small |brief )?update (on|about) (that|this|the) (task|job|team job)\b",l))
def team_job_card(j):return {"type":"team_job","id":j["id"],"task":j["task"],"status":j["status"],"project_id":j.get("project_id"),"agents":j.get("agent_names",[]),"handoffs":[{"id":h["id"],"agent":h["to_agent_name"],"status":h["status"],"error":h.get("error"),"attempts":h.get("attempts",0),"summary":h.get("progress_summary"),"status_checked_at":h.get("status_checked_at")} for h in j.get("handoffs",[])],"final_output":j.get("final_output"),"created_at":j.get("created_at"),"started_at":j.get("started_at"),"finished_at":j.get("finished_at"),"updated_at":j.get("updated_at"),"status_checked_at":j.get("status_checked_at")}
def _status_message(j):return "\n".join([f"Team task is {j.get('status','unknown')}."]+[f"{h.get('to_agent_name') or 'Agent'}: {h.get('progress_summary') or _fallback_status(j,h)}" for h in j.get("handoffs",[])])
def _finish_job(jid,results,only_ids=None):
    by={hid:(out,err) for hid,out,err in results}
    def finish(j):
        for h in j["handoffs"]:
            if only_ids is not None and h["id"] not in only_ids:continue
            out,err=by.get(h["id"],(None,"No result"));h.update(result=out,error=err,finished_at=_now(),status="failed" if err else "completed");h["progress_summary"]=_fallback_status(j,h);h["status_checked_at"]=_now()
        done=[h for h in j["handoffs"] if h.get("status")=="completed"];bad=[h for h in j["handoffs"] if h.get("status")=="failed"];active=[h for h in j["handoffs"] if h.get("status") in {"queued","working"}]
        j["status"]="working" if active else "partial" if done and bad else "completed" if done and len(done)==len(j["handoffs"]) else "failed"
        if not active:j["finished_at"]=_now()
        outputs=[f"{h['to_agent_name']}:\n{h['result']}" for h in j["handoffs"] if h.get("status")=="completed" and h.get("result")];j["final_output"]="\n\n---\n\n".join(outputs) if outputs else None
    u=_mutate(jid,finish)
    if u:remember_global_result("",team_job_card(u))
async def _execute(jid,only_ids=None):
    j=get_team_job(jid)
    if not j:return
    targets=[h for h in j["handoffs"] if only_ids is None or h["id"] in only_ids]
    if not targets:return
    _mutate(jid,lambda x:x.update(status="working",started_at=x.get("started_at") or _now()));_finish_job(jid,await asyncio.gather(*[_worker(jid,h) for h in targets]),only_ids)
def _thread_run(jid,only_ids=None):
    try:asyncio.run(_execute(jid,only_ids))
    finally:_RUNNING.pop(jid,None)
def start_team_job(jid,only_ids=None):
    if jid in _RUNNING and _RUNNING[jid].is_alive():return
    t=threading.Thread(target=_thread_run,args=(jid,only_ids),daemon=True,name=f"agentie-{jid}");_RUNNING[jid]=t;t.start()
def retry_team_worker(jid,agent_name):
    j=get_team_job(jid)
    if not j:raise ValueError("Team job was not found.")
    h=next((h for h in j["handoffs"] if str(h.get("to_agent_name","")).casefold()==agent_name.casefold()),None)
    if not h:raise ValueError(f"Agent {agent_name} is not part of this team job.")
    if h.get("status")!="failed":raise ValueError(f"{h['to_agent_name']} is not failed and does not need a retry.")
    hid=h["id"];_mutate(jid,lambda x:[q.update(status="queued",error=None,progress_summary=None,status_checked_at=None) for q in x["handoffs"] if q["id"]==hid]);start_team_job(jid,{hid});return get_team_job(jid) or j

def route_team_command(message):
    text=" ".join(message.strip().split());lower=text.lower().strip(" .?!")
    project=route_project_command(text)
    if project is not None:return project
    if _looks_like_status_request(lower):
        m=re.search(r"\b(team_[a-z0-9]+)\b",lower);j=get_team_job(m.group(1)) if m else _latest_job_for_status()
        if not j:return None
        try:j=request_team_status(j["id"])
        except ValueError:return {"message":"Team job not found.","card":None}
        return {"message":_status_message(j),"card":team_job_card(j)}
    if lower in {"show team jobs","list team jobs","show handoffs","list handoffs","show delegations"}:
        items=list_team_jobs();return {"message":f"There are {len(items)} team job(s).","card":{"type":"team_jobs","items":[team_job_card(x) for x in items]}}
    m=re.match(r"^(show|check|inspect)\s+(team job|handoff|delegation)\s+([a-z0-9_]+)[.!?]?$",text,re.I)
    if m:
        j=get_team_job(m.group(3));return {"message":"Team job not found.","card":None} if not j else {"message":f"Team job {j['id']} is {j['status']}.","card":team_job_card(j)}
    retry=re.match(r"^(retry|try again)\s+(.+?)\s+(on|for|in)\s+(team job\s+)?([a-z0-9_]+)[.!?]?$",text,re.I)
    if retry:
        try:j=retry_team_worker(retry.group(5),retry.group(2).strip())
        except ValueError as exc:return {"message":str(exc),"card":None}
        return {"message":f"Retrying {retry.group(2).strip()} on team job {j['id']}.","card":team_job_card(j)}
    together=re.match(r"^(have|ask|tell)\s+(.+?)\s+(to\s+)?work\s+together\s+(on|to)\s+(.+?)[.!?]?$",text,re.I)
    if together:
        raw=together.group(2);task=together.group(5);agents,missing=_resolve_names(raw)
        if missing:return _missing_agent_choice(missing,task,[x.strip() for x in re.split(r"\s*,\s*|\s+and\s+",raw,flags=re.I)])
        j=create_team_job(task,agents);start_team_job(j["id"]);card=team_job_card(j);remember_global_result("",card);return {"message":f"Started team job {j['id']} with {', '.join(j['agent_names'])} working simultaneously.","card":card}
    delegate=re.match(r"^(delegate|hand off|handoff)\s+(.+?)\s+to\s+(.+?)[.!?]?$",text,re.I)
    if delegate:
        task=delegate.group(2);raw=delegate.group(3);agents,missing=_resolve_names(raw)
        if missing:return _missing_agent_choice(missing,task,[x.strip() for x in re.split(r"\s*,\s*|\s+and\s+",raw,flags=re.I)])
        j=create_team_job(task,agents);start_team_job(j["id"]);card=team_job_card(j);remember_global_result("",card);return {"message":f"Delegated the task to {', '.join(j['agent_names'])} as team job {j['id']}.","card":card}
    return None