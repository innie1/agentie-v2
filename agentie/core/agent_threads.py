from __future__ import annotations

import json,re,uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from agentie.core.agent_registry import get_agent,list_agents
from agentie.core.team_orchestrator import create_team_job,get_team_job,start_team_job

WORKSPACE=Path.cwd()/"workspace";THREADS=WORKSPACE/"agent_threads.json"
def _now():return datetime.now().astimezone().isoformat(timespec="seconds")
def _load():
    try:value=json.loads(THREADS.read_text(encoding="utf-8")) if THREADS.exists() else [];return value if isinstance(value,list) else []
    except Exception:return []
def _save(items):THREADS.parent.mkdir(parents=True,exist_ok=True);THREADS.write_text(json.dumps(items,indent=2,ensure_ascii=False),encoding="utf-8")
def _clean(value,limit=3000):return " ".join(str(value or "").strip().split())[:limit]
def list_threads(agent_id:str|None=None)->list[dict[str,Any]]:
    items=_load()
    if agent_id:items=[x for x in items if str(agent_id) in {str(y) for y in x.get("participant_ids") or []}]
    return list(reversed(items))
def get_thread(name_or_id:str)->dict[str,Any]|None:
    key=str(name_or_id or "").strip().casefold()
    for item in _load():
        if str(item.get("id") or "").casefold()==key or str(item.get("name") or "").casefold()==key:return item
    return None
def create_thread(name:str,participants:list[str])->dict[str,Any]:
    name=_clean(name,120)
    if not name:raise ValueError("Thread name is required.")
    resolved=[]
    for raw in participants:
        agent=get_agent(raw)
        if not agent:raise ValueError(f"Agent {raw} was not found.")
        if all(x["id"]!=agent["id"] for x in resolved):resolved.append(agent)
    if not resolved:raise ValueError("Add at least one agent to the thread.")
    items=_load();existing=next((x for x in items if str(x.get("name") or "").casefold()==name.casefold()),None)
    if existing:return existing
    now=_now();item={"id":"thr_"+uuid.uuid4().hex[:10],"name":name,"participant_ids":[x["id"] for x in resolved],"participant_names":[x["name"] for x in resolved],"messages":[],"created_at":now,"updated_at":now};items.append(item);_save(items);return item
def add_participant(thread_id:str,agent_id_or_name:str)->dict[str,Any]:
    items=_load();thread=next((x for x in items if str(x.get("id"))==str(thread_id) or str(x.get("name","")).casefold()==str(thread_id).casefold()),None)
    if not thread:raise ValueError("Agent thread was not found.")
    agent=get_agent(agent_id_or_name)
    if not agent:raise ValueError("Agent was not found.")
    if agent["id"] not in thread.setdefault("participant_ids",[]):thread["participant_ids"].append(agent["id"]);thread.setdefault("participant_names",[]).append(agent["name"]);thread["updated_at"]=_now();_save(items)
    return thread
def post_message(thread_id:str,sender_type:str,sender_id:str|None,sender_name:str,message:str,metadata:dict[str,Any]|None=None)->dict[str,Any]:
    items=_load();thread=next((x for x in items if str(x.get("id"))==str(thread_id) or str(x.get("name","")).casefold()==str(thread_id).casefold()),None)
    if not thread:raise ValueError("Agent thread was not found.")
    row={"id":"msg_"+uuid.uuid4().hex[:10],"sender_type":sender_type,"sender_id":sender_id,"sender_name":_clean(sender_name,120),"message":str(message or "").strip()[:12000],"metadata":metadata or {},"at":_now()};thread.setdefault("messages",[]).append(row);thread["messages"]=thread["messages"][-500:];thread["updated_at"]=_now();_save(items);return row
def remove_agent_from_threads(agent_id:str)->int:
    items=_load();changed=0
    for thread in items:
        ids=[str(x) for x in thread.get("participant_ids") or []]
        if str(agent_id) not in ids:continue
        index=ids.index(str(agent_id));thread["participant_ids"].pop(index)
        if index<len(thread.get("participant_names") or []):thread["participant_names"].pop(index)
        thread["updated_at"]=_now();changed+=1
    if changed:_save(items)
    return changed
def _sync_jobs(thread:dict[str,Any])->dict[str,Any]:
    result=dict(thread);messages=[]
    for row in thread.get("messages") or []:
        copy=dict(row);job_id=(row.get("metadata") or {}).get("team_job_id")
        if job_id:
            job=get_team_job(str(job_id))
            if job:copy["job"]={"id":job["id"],"status":job.get("status"),"agents":job.get("agent_names") or [],"final_output":job.get("final_output"),"handoffs":[{"agent":h.get("to_agent_name"),"status":h.get("status"),"result":h.get("result"),"error":h.get("error")} for h in job.get("handoffs") or []]}
        messages.append(copy)
    result["messages"]=messages;return result
def thread_card(thread:dict[str,Any])->dict[str,Any]:
    value=_sync_jobs(thread);return {"type":"agent_thread","id":value.get("id"),"name":value.get("name"),"participant_ids":value.get("participant_ids") or [],"participants":value.get("participant_names") or [],"messages":value.get("messages") or [],"updated_at":value.get("updated_at")}
def threads_card(items:list[dict[str,Any]])->dict[str,Any]:return {"type":"agent_threads","items":[{"id":x.get("id"),"name":x.get("name"),"participants":x.get("participant_names") or [],"updated_at":x.get("updated_at"),"message_count":len(x.get("messages") or [])} for x in items]}

def route_thread_command(message:str)->dict[str,Any]|None:
    text=" ".join(str(message or "").strip().split());lower=text.casefold().strip(" .?!")
    if lower in {"show agent chats","show group chats","list agent chats","list group chats","agent chats","group chats","team chats"}:
        items=list_threads();return {"message":f"You have {len(items)} agent collaboration thread(s).","card":threads_card(items)}
    m=re.match(r"^(?:create|make|start)\s+(?:an?\s+)?(?:agent|group|team)\s+chat\s+with\s+(.+?)\s+(?:called|named)\s+(.+)$",text,re.I)
    if m:
        names=[x.strip(' .?!\"“”') for x in re.split(r"\s*,\s*|\s+and\s+",m.group(1),flags=re.I) if x.strip()]
        try:thread=create_thread(m.group(2).strip(' .?!\"“”'),names)
        except ValueError as exc:return {"message":str(exc),"card":None}
        return {"message":f"Created agent chat “{thread['name']}” with {', '.join(thread['participant_names'])}.","card":thread_card(thread)}
    m=re.match(r"^(?:show|open)\s+(?:agent|group|team)?\s*chat\s+(.+)$",text,re.I)
    if m:
        thread=get_thread(m.group(1).strip(' .?!\"“”'));return {"message":"Agent chat was not found.","card":None} if not thread else {"message":f"Here is “{thread['name']}”.","card":thread_card(thread)}
    m=re.match(r"^(?:message|post to|say in)\s+(?:agent|group|team)?\s*chat\s+(.+?)\s*:\s*(.+)$",text,re.I)
    if m:
        thread=get_thread(m.group(1).strip(' .?!\"“”'))
        if not thread:return {"message":"Agent chat was not found.","card":None}
        post_message(thread["id"],"user",None,"User",m.group(2));return {"message":f"Posted to “{thread['name']}”.","card":thread_card(get_thread(thread["id"]) or thread)}
    # Asking an agent inside a thread creates a real existing team job and links
    # its live result into the thread; the thread is not a second execution engine.
    m=re.match(r"^(?:ask|tell|have)\s+(.+?)\s+in\s+(?:agent|group|team)?\s*chat\s+(.+?)\s+(?:to\s+)?(.+)$",text,re.I)
    if m:
        agent=get_agent(m.group(1).strip());thread=get_thread(m.group(2).strip(' .?!\"“”'));task=m.group(3).strip()
        if not agent:return {"message":"Agent was not found.","card":None}
        if not thread:return {"message":"Agent chat was not found.","card":None}
        if agent["id"] not in thread.get("participant_ids",[]):return {"message":f"{agent['name']} is not a participant in that chat.","card":None}
        job=create_team_job(task,[agent],requested_by="user");start_team_job(job["id"]);post_message(thread["id"],"user",None,"User",f"@{agent['name']} {task}",{"team_job_id":job["id"],"to_agent_id":agent["id"]});return {"message":f"Asked {agent['name']} in “{thread['name']}”.","card":thread_card(get_thread(thread["id"]) or thread)}
    return None
