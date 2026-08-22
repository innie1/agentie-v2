from __future__ import annotations

import json,re,uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from agentie.core.agent_registry import get_agent
from agentie.core.team_orchestrator import create_team_job,get_team_job,start_team_job

WORKSPACE=Path.cwd()/"workspace";THREADS=WORKSPACE/"agent_threads.json"
_REACTIONS={"👍","👎","✅","❗","❤️","🎉"}
def _now():return datetime.now().astimezone().isoformat(timespec="seconds")
def _load():
    try:value=json.loads(THREADS.read_text(encoding="utf-8")) if THREADS.exists() else [];return value if isinstance(value,list) else []
    except Exception:return []
def _save(items):THREADS.parent.mkdir(parents=True,exist_ok=True);THREADS.write_text(json.dumps(items,indent=2,ensure_ascii=False),encoding="utf-8")
def _clean(value,limit=3000):return " ".join(str(value or "").strip().split())[:limit]
def _publish(event_type:str,payload:dict[str,Any],dedupe_key:str|None=None)->None:
    try:
        from agentie.core.automation_events import publish_event
        publish_event(event_type,payload,source="agent_threads",dedupe_key=dedupe_key)
    except Exception:pass

def list_threads(agent_id:str|None=None)->list[dict[str,Any]]:
    items=_load()
    if agent_id:items=[x for x in items if str(agent_id) in {str(y) for y in x.get("participant_ids") or []}]
    return list(reversed(items))
def get_thread(name_or_id:str)->dict[str,Any]|None:
    key=str(name_or_id or "").strip().casefold()
    for item in _load():
        if str(item.get("id") or "").casefold()==key or str(item.get("name") or "").casefold()==key:return item
    return None
def _stored_thread(items:list[dict[str,Any]],thread_id:str)->dict[str,Any]|None:
    key=str(thread_id or "").casefold();return next((x for x in items if str(x.get("id"))==str(thread_id) or str(x.get("name","")).casefold()==key),None)
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
def ensure_direct_thread(first:str,second:str)->dict[str,Any]:
    a=get_agent(first);b=get_agent(second)
    if not a or not b:raise ValueError("Both agents must exist before creating a direct agent chat.")
    wanted={str(a["id"]),str(b["id"])}
    for item in _load():
        ids={str(x) for x in item.get("participant_ids") or []}
        if ids==wanted and len(ids)==2:return item
    return create_thread(f"{a['name']} ↔ {b['name']}",[a["id"],b["id"]])
def add_participant(thread_id:str,agent_id_or_name:str)->dict[str,Any]:
    items=_load();thread=_stored_thread(items,thread_id)
    if not thread:raise ValueError("Agent thread was not found.")
    agent=get_agent(agent_id_or_name)
    if not agent:raise ValueError("Agent was not found.")
    if agent["id"] not in thread.setdefault("participant_ids",[]):thread["participant_ids"].append(agent["id"]);thread.setdefault("participant_names",[]).append(agent["name"]);thread["updated_at"]=_now();_save(items)
    return thread

def _mentioned_agents(thread:dict[str,Any],message:str)->list[dict[str,Any]]:
    found=[];text=str(message or "")
    for aid,name in zip(thread.get("participant_ids") or [],thread.get("participant_names") or []):
        if re.search(rf"(?<!\w)@{re.escape(str(name))}(?![A-Za-z0-9_-])",text,re.I):
            agent=get_agent(str(aid))
            if agent:found.append(agent)
    return found
def _task_without_mentions(message:str,agents:list[dict[str,Any]])->str:
    task=str(message or "")
    for agent in agents:task=re.sub(rf"(?<!\w)@{re.escape(str(agent.get('name') or ''))}(?![A-Za-z0-9_-])"," ",task,flags=re.I)
    return _clean(task,12000).strip(" ,.;:-") or _clean(message,12000)
def _interaction_mode(task:str)->str:
    text=" ".join(str(task or "").strip().split());lower=text.casefold()
    if not text:return "chat"
    task_signal=re.search(r"\b(?:research|investigate|compare|analy[sz]e|review|audit|create|write|draft|build|make|design|calculate|check|verify|summari[sz]e|plan|evaluate|recommend|prepare|send|email|post|publish|edit|fix|implement|test|report|find|search|look up|work on|give me|list|explain|delegate|coordinate)\b",lower)
    if task_signal:return "task"
    return "chat" if len(text)<=320 else "task"
def _visible_agent_reply(value:str,mode:str="task")->str:
    text=str(value or "").strip()
    if not text:return "Completed the assigned task."
    text=re.split(r"(?im)^\s*#{1,6}\s*Handoff Summary\b",text,maxsplit=1)[0].strip()
    text=re.sub(r"(?im)^\s*#{1,6}\s*(?:Deliverable|Response|Answer)\s*:?[ \t]*\n?","",text).strip()
    text=re.sub(r"(?m)^\s*---+\s*$","",text).strip()
    if mode=="chat":
        text=re.split(r"(?im)^\s*#{1,6}\s*(?:Current Status|Role Focus|Next Steps?|Scope|Verification Framework|Facts|Opinions|Recommendations|Risks?\s*&\s*Uncertainties)\b",text,maxsplit=1)[0].strip()
    return text[:12000] or "Completed the assigned task."

def post_message(thread_id:str,sender_type:str,sender_id:str|None,sender_name:str,message:str,metadata:dict[str,Any]|None=None,reply_to_message_id:str|None=None)->dict[str,Any]:
    items=_load();thread=_stored_thread(items,thread_id)
    if not thread:raise ValueError("Agent thread was not found.")
    meta=dict(metadata or {})
    if reply_to_message_id:
        if not any(str(x.get("id"))==str(reply_to_message_id) for x in thread.get("messages") or []):raise ValueError("Reply target message was not found in this chat.")
        meta["reply_to_message_id"]=str(reply_to_message_id)
    if sender_type=="user" and not meta.get("team_job_id"):
        agents=_mentioned_agents(thread,message)
        if agents:
            task=_task_without_mentions(message,agents);mode=_interaction_mode(task);job=create_team_job(task,agents,requested_by="user",interaction_mode=mode);start_team_job(job["id"]);meta.update({"team_job_id":job["id"],"to_agent_ids":[a["id"] for a in agents],"mentions":[a["name"] for a in agents],"materialize_replies":True,"interaction_mode":mode})
    row={"id":"msg_"+uuid.uuid4().hex[:10],"sender_type":sender_type,"sender_id":sender_id,"sender_name":_clean(sender_name,120),"message":str(message or "").strip()[:12000],"metadata":meta,"reactions":[],"at":_now()};thread.setdefault("messages",[]).append(row);thread["messages"]=thread["messages"][-500:];thread["updated_at"]=_now();_save(items)
    _publish("agent_thread.message",{"thread_id":thread["id"],"thread_name":thread.get("name"),"message_id":row["id"],"sender_type":sender_type,"sender_id":sender_id,"sender_name":row["sender_name"],"message":row["message"],"team_job_id":meta.get("team_job_id"),"reply_to_message_id":meta.get("reply_to_message_id")},f"thread-message:{row['id']}")
    return row
def reply_to_message(thread_id:str,message_id:str,message:str,*,sender_type:str="user",sender_id:str|None=None,sender_name:str="User")->dict[str,Any]:
    return post_message(thread_id,sender_type,sender_id,sender_name,message,reply_to_message_id=message_id)
def react_to_message(thread_id:str,message_id:str,reaction:str,*,actor_type:str="user",actor_id:str|None=None,actor_name:str="User")->dict[str,Any]:
    if reaction not in _REACTIONS:raise ValueError("Reaction must be one of: "+" ".join(sorted(_REACTIONS)))
    items=_load();thread=_stored_thread(items,thread_id)
    if not thread:raise ValueError("Agent chat was not found.")
    row=next((x for x in thread.get("messages") or [] if str(x.get("id"))==str(message_id)),None)
    if not row:raise ValueError("Message was not found in this chat.")
    reactions=row.setdefault("reactions",[]);actor_key=f"{actor_type}:{actor_id or actor_name}";existing=next((x for x in reactions if x.get("actor_key")==actor_key and x.get("reaction")==reaction),None)
    if existing:reactions.remove(existing);active=False
    else:reactions.append({"reaction":reaction,"actor_type":actor_type,"actor_id":actor_id,"actor_name":_clean(actor_name,120),"actor_key":actor_key,"at":_now()});active=True
    thread["updated_at"]=_now();_save(items);_publish("agent_thread.reaction",{"thread_id":thread["id"],"message_id":message_id,"reaction":reaction,"active":active,"actor_type":actor_type,"actor_id":actor_id,"actor_name":actor_name},f"thread-reaction:{message_id}:{actor_key}:{reaction}:{active}")
    return row

def agent_to_agent_task(sender_id_or_name:str,target_id_or_name:str,task:str,thread_id:str|None=None)->dict[str,Any]:
    sender=get_agent(sender_id_or_name);target=get_agent(target_id_or_name)
    if not sender or not target:raise ValueError("Sender and target agents must both exist.")
    if sender["id"]==target["id"]:raise ValueError("An agent cannot delegate a task to itself.")
    if not bool((sender.get("permissions") or {}).get("delegate")):raise ValueError(f"{sender['name']} is not allowed to delegate work to other agents.")
    thread=get_thread(thread_id) if thread_id else ensure_direct_thread(sender["id"],target["id"])
    if not thread:raise ValueError("Agent chat was not found.")
    for agent in (sender,target):
        if agent["id"] not in thread.get("participant_ids",[]):add_participant(thread["id"],agent["id"]);thread=get_thread(thread["id"]) or thread
    task=_clean(task,12000)
    if not task:raise ValueError("A task is required.")
    job=create_team_job(task,[target],requested_by=sender["name"],interaction_mode="task");start_team_job(job["id"])
    row=post_message(thread["id"],"agent",sender["id"],sender["name"],f"@{target['name']} {task}",{"team_job_id":job["id"],"to_agent_ids":[target["id"]],"mentions":[target["name"]],"materialize_replies":True,"source":"agent_delegate","interaction_mode":"task"})
    return {"thread":get_thread(thread["id"]) or thread,"message":row,"job":job,"sender":sender,"target":target}
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

def _materialize_job_results(thread_id:str)->dict[str,Any]|None:
    items=_load();thread=_stored_thread(items,thread_id)
    if not thread:return None
    changed=False;new_replies=[]
    for origin in list(thread.get("messages") or []):
        meta=origin.setdefault("metadata",{});job_id=meta.get("team_job_id")
        if not job_id or meta.get("source")=="team_job" or not bool(meta.get("materialize_replies",str(origin.get("sender_type") or "")=="user")):continue
        job=get_team_job(str(job_id))
        if not job:continue
        mode=str(job.get("interaction_mode") or meta.get("interaction_mode") or _interaction_mode(str(job.get("task") or "")))
        emitted={str(x) for x in meta.get("materialized_handoff_ids") or []}
        for handoff in job.get("handoffs") or []:
            status=str(handoff.get("status") or "")
            if status not in {"completed","failed","cancelled"}:continue
            hid=str(handoff.get("id") or "")
            if not hid or hid in emitted:continue
            name=str(handoff.get("to_agent_name") or "Agent");agent_id=str(handoff.get("to_agent_id") or "") or None;body=_visible_agent_reply(str(handoff.get("result") or "Completed the assigned task."),mode) if status=="completed" else f"{status.title()}: {str(handoff.get('error') or 'The assigned task did not complete.')[:1500]}"
            reply={"id":"msg_"+uuid.uuid4().hex[:10],"sender_type":"agent","sender_id":agent_id,"sender_name":name,"message":body[:12000],"reactions":[],"metadata":{"team_job_id":job["id"],"handoff_id":hid,"reply_to_message_id":origin.get("id"),"source":"team_job","status":status,"interaction_mode":mode},"at":handoff.get("finished_at") or job.get("finished_at") or _now()}
            thread.setdefault("messages",[]).append(reply);new_replies.append(reply);emitted.add(hid);changed=True
        meta["materialized_handoff_ids"]=sorted(emitted)
    if changed:
        thread["messages"]=thread["messages"][-500:];thread["updated_at"]=_now();_save(items)
        for reply in new_replies:_publish("agent_thread.agent_reply",{"thread_id":thread["id"],"thread_name":thread.get("name"),"message_id":reply["id"],"sender_id":reply.get("sender_id"),"sender_name":reply.get("sender_name"),"message":reply.get("message"),"team_job_id":(reply.get("metadata") or {}).get("team_job_id"),"reply_to_message_id":(reply.get("metadata") or {}).get("reply_to_message_id"),"status":(reply.get("metadata") or {}).get("status")},f"thread-reply:{reply['id']}")
    return thread

def _sync_jobs(thread:dict[str,Any])->dict[str,Any]:
    thread=_materialize_job_results(str(thread.get("id"))) or thread;result=dict(thread);messages=[]
    for row in thread.get("messages") or []:
        copy=dict(row);meta=row.get("metadata") or {};job_id=meta.get("team_job_id")
        if job_id:
            job=get_team_job(str(job_id));mode=str((job or {}).get("interaction_mode") or meta.get("interaction_mode") or _interaction_mode(str((job or {}).get("task") or "")))
            if meta.get("source")=="team_job":copy["message"]=_visible_agent_reply(str(copy.get("message") or ""),mode)
            if job and mode!="chat" and meta.get("source")!="team_job":copy["job"]={"id":job["id"],"status":job.get("status"),"agents":job.get("agent_names") or [],"interaction_mode":mode,"replan_count":job.get("replan_count",0),"handoffs":[{"agent":h.get("to_agent_name"),"status":h.get("status"),"error":h.get("error"),"recovery_of":h.get("recovery_of")} for h in job.get("handoffs") or []]}
        messages.append(copy)
    result["messages"]=messages;return result
def thread_card(thread:dict[str,Any])->dict[str,Any]:
    value=_sync_jobs(thread);return {"type":"agent_thread","id":value.get("id"),"name":value.get("name"),"participant_ids":value.get("participant_ids") or [],"participants":value.get("participant_names") or [],"messages":value.get("messages") or [],"updated_at":value.get("updated_at")}
def threads_card(items:list[dict[str,Any]])->dict[str,Any]:return {"type":"agent_threads","items":[{"id":x.get("id"),"name":x.get("name"),"participants":x.get("participant_names") or [],"updated_at":x.get("updated_at"),"message_count":len(x.get("messages") or [])} for x in items]}

def route_thread_command(message:str)->dict[str,Any]|None:
    text=" ".join(str(message or "").strip().split());lower=text.casefold().strip(" .?!")
    from agentie.core.platform_router import route_platform_command
    platform=route_platform_command(text)
    if platform is not None:return platform
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
        row=post_message(thread["id"],"user",None,"User",m.group(2));mentions=(row.get("metadata") or {}).get("mentions") or [];verb=f"Asked {', '.join(mentions)} in" if mentions else "Posted to";return {"message":f"{verb} “{thread['name']}”.","card":thread_card(get_thread(thread["id"]) or thread)}
    m=re.match(r"^(?:reply in|reply to)\s+(?:agent|group|team)?\s*chat\s+(.+?)\s+(?:to\s+)?(msg_[a-z0-9]+)\s*:\s*(.+)$",text,re.I)
    if m:
        thread=get_thread(m.group(1).strip())
        if not thread:return {"message":"Agent chat was not found.","card":None}
        try:reply_to_message(thread["id"],m.group(2),m.group(3))
        except ValueError as exc:return {"message":str(exc),"card":None}
        return {"message":f"Replied in “{thread['name']}”.","card":thread_card(get_thread(thread["id"]) or thread)}
    m=re.match(r"^react\s+(👍|👎|✅|❗|❤️|🎉)\s+to\s+(msg_[a-z0-9]+)\s+in\s+(?:agent|group|team)?\s*chat\s+(.+)$",text,re.I)
    if m:
        thread=get_thread(m.group(3).strip(' .?!\"“”'))
        if not thread:return {"message":"Agent chat was not found.","card":None}
        try:react_to_message(thread["id"],m.group(2),m.group(1))
        except ValueError as exc:return {"message":str(exc),"card":None}
        return {"message":f"Updated reaction in “{thread['name']}”.","card":thread_card(get_thread(thread["id"]) or thread)}
    m=re.match(r"^(?:ask|tell|have)\s+(.+?)\s+in\s+(?:agent|group|team)?\s*chat\s+(.+?)\s+(?:to\s+)?(.+)$",text,re.I)
    if m:
        agent=get_agent(m.group(1).strip());thread=get_thread(m.group(2).strip(' .?!\"“”'));task=m.group(3).strip()
        if not agent:return {"message":"Agent was not found.","card":None}
        if not thread:return {"message":"Agent chat was not found.","card":None}
        if agent["id"] not in thread.get("participant_ids",[]):return {"message":f"{agent['name']} is not a participant in that chat.","card":None}
        mode=_interaction_mode(task);job=create_team_job(task,[agent],requested_by="user",interaction_mode=mode);start_team_job(job["id"]);post_message(thread["id"],"user",None,"User",f"@{agent['name']} {task}",{"team_job_id":job["id"],"to_agent_ids":[agent["id"]],"mentions":[agent["name"]],"materialize_replies":True,"interaction_mode":mode});return {"message":f"Asked {agent['name']} in “{thread['name']}”.","card":thread_card(get_thread(thread["id"]) or thread)}
    return None
