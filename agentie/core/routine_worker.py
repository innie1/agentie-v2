from __future__ import annotations

import asyncio,json,re
from datetime import datetime
from pathlib import Path
from typing import Any

from agentie.core.automation_events import close_event,mark_delivered,pending_events
from agentie.core.browser_monitor import capture_website,routine_always_show,website_routine_target
from agentie.core.job_engine import create_job,job_card,poll_job_completion_events,start_job
from agentie.core.routine_engine import claim_due_routines,event_routines_for,mark_event_routine_claimed,record_run
from agentie.core.runner import run_agent
from agentie.core.team_orchestrator import poll_team_completion_events
from agentie.tools.approval_tools import poll_background_approval_events

WORKSPACE=Path.cwd()/"workspace";EVENTS=WORKSPACE/"routine_events.json";_TASK:asyncio.Task|None=None
_SECRET_KEY=re.compile(r"(?:password|passwd|secret|token|authorization|cookie|credential|oauth|bearer|api[_-]?key|access[_-]?key|private[_-]?key)",re.I)
def _load_events()->list[dict[str,Any]]:
    try:return json.loads(EVENTS.read_text(encoding="utf-8")) if EVENTS.exists() else []
    except Exception:return []
def _save_events(items:list[dict[str,Any]])->None:EVENTS.parent.mkdir(parents=True,exist_ok=True);EVENTS.write_text(json.dumps(items[-200:],indent=2,ensure_ascii=False),encoding="utf-8")
def _push(event:dict[str,Any])->None:items=_load_events();items.append(event);_save_events(items)
def poll_routine_events()->list[dict[str,Any]]:
    items=_load_events()
    if items:_save_events([])
    try:
        jobs=poll_job_completion_events();items.extend(jobs)
        for event in jobs:
            card=event.get("card") if isinstance(event,dict) else None
            for artifact in (card.get("artifacts") or []) if isinstance(card,dict) else []:
                if isinstance(artifact,dict):items.append({"message":f"Generated file: {artifact.get('document_name') or artifact.get('name') or 'artifact'}.","card":artifact})
    except Exception:pass
    try:items.extend(poll_team_completion_events())
    except Exception:pass
    try:items.extend(poll_background_approval_events())
    except Exception:pass
    return items
async def _runner(instruction:str,specialist:str,session_id:str)->str:return await run_agent(instruction,specialist,session_id)
def _routine_session(routine:dict[str,Any])->str:
    owner=str(routine.get("owner_agent_id") or "").strip();return f"agent:{owner}:routine:{routine['id']}" if owner else f"routine:{routine['id']}"

def _safe_event_value(key:str,value:Any,depth:int=0)->Any:
    if _SECRET_KEY.search(str(key or "")):return "<redacted>"
    if isinstance(value,(str,int,float,bool)) or value is None:
        text=value if not isinstance(value,str) else value[:1200]
        return text
    if depth>=2:return f"<{type(value).__name__}>"
    if isinstance(value,dict):return {str(k)[:100]:_safe_event_value(str(k),v,depth+1) for k,v in list(value.items())[:40]}
    if isinstance(value,list):return [_safe_event_value(key,v,depth+1) for v in value[:20]]
    return f"<{type(value).__name__}>"
def _safe_event_context(event:dict[str,Any]|None)->dict[str,Any]:
    if not event:return {}
    payload=dict(event.get("payload") or {});safe={str(k)[:100]:_safe_event_value(str(k),v) for k,v in list(payload.items())[:60]}
    return {"event_id":event.get("id"),"event_type":event.get("type"),"source":event.get("source"),"payload":safe}
def _event_instruction(action:str,event:dict[str,Any]|None)->str:
    context=_safe_event_context(event)
    if not context:return action
    return action+"\n\nAUTOMATION EVENT CONTEXT (use this event as the input to the routine; do not invent missing fields):\n"+json.dumps(context,ensure_ascii=False,default=str)[:12000]
def _skill_event_inputs(event:dict[str,Any]|None)->dict[str,Any]:
    payload=dict((_safe_event_context(event).get("payload") or {}));out={}
    for key,value in payload.items():
        if isinstance(value,(str,int,float,bool)):out[str(key)]=value
        elif value is not None:out[str(key)]=json.dumps(value,ensure_ascii=False,default=str)[:3000]
    return out

async def _run_website_routine(routine:dict[str,Any],url:str,event:dict[str,Any]|None=None)->None:
    try:
        result=await capture_website(url,track_change=True);changed=bool(result.get("changed"));first=bool(result.get("first_check"));always=routine_always_show(str(routine.get("action") or ""));status="changed" if changed else "unchanged";record_run(routine["id"],None,status,{"event_id":(event or {}).get("id"),"trigger_type":routine.get("trigger_type","schedule")})
        if first or changed or always:_push({"message":f"Website routine: {routine['name']}. {result.get('message','')}","card":result.get("card")})
    except Exception as exc:record_run(routine["id"],None,"failed",{"event_id":(event or {}).get("id")});_push({"message":f"Website routine “{routine['name']}” failed: {exc}","card":None})
def _browser_skill_status(result:dict[str,Any])->str:
    explicit=str(result.get("status") or "").strip()
    if explicit:return explicit
    card=result.get("card") if isinstance(result.get("card"),dict) else {};ctype=str(card.get("type") or "");title=str(card.get("title") or "").casefold();message=str(result.get("message") or "").casefold()
    if ctype=="browser_approval":return "awaiting_approval"
    if "protected value" in message or "complete the protected field" in message:return "needs_input"
    if "failed" in title or "failed:" in message:return "failed"
    return "completed"
def _retry_enabled(routine:dict[str,Any])->bool:return str(routine.get("failure_policy") or "report").casefold() in {"retry","retry_once","retry-then-report","retry_then_report"}
def _retry_safe(result:dict[str,Any])->bool:
    if str(result.get("status") or "")!="failed":return False
    from agentie.core.failure_recovery import recovery_policy
    text=str(result.get("message") or (result.get("run") or {}).get("error") or "");return bool(recovery_policy(text,1).get("automatic"))
async def _execute_linked_skill_once(routine:dict[str,Any],skill:dict[str,Any],inputs:dict[str,Any],session:str)->tuple[dict[str,Any],str]:
    skill_id=str(skill["id"])
    if skill.get("source_workflow_id"):
        from agentie.core.workflow_browser_runtime import _run_skill
        invocation=skill_id
        if inputs:invocation += " with inputs " + ", ".join(f"{k}={v}" for k,v in inputs.items())
        result=await _run_skill(invocation,session);return result,_browser_skill_status(result)
    from agentie.core.workflow_skill_runtime import execute_workflow_skill
    result=await execute_workflow_skill(skill_id,session,inputs=inputs,requested_by="routine",source=f"routine:{routine['id']}");return result,str(result.get("status") or "completed")
async def _run_linked_skill(routine:dict[str,Any],event:dict[str,Any]|None=None)->None:
    skill_id=str(routine.get("skill_id") or "").strip()
    if not skill_id:return
    if not routine.get("owner_agent_id"):
        record_run(routine["id"],None,"failed",{"skill_id":skill_id,"event_id":(event or {}).get("id")});_push({"message":f"Routine “{routine['name']}” cannot run Skill {skill_id} until it has an owner agent.","card":None});return
    try:
        from agentie.core.workflow_skills import get_workflow_skill
        skill=get_workflow_skill(skill_id)
        if not skill:raise ValueError(f"Skill {skill_id} was not found.")
        inputs=_skill_event_inputs(event);session=_routine_session(routine);result,status=await _execute_linked_skill_once(routine,skill,inputs,session);retried=False
        if status=="failed" and _retry_enabled(routine) and _retry_safe(result):
            retried=True;record_run(routine["id"],None,"retrying",{"skill_id":skill_id,"event_id":(event or {}).get("id"),"trigger_type":routine.get("trigger_type","schedule")});result,status=await _execute_linked_skill_once(routine,skill,inputs,session)
        if status not in {"completed","failed","awaiting_approval","needs_input","needs_access","inactive","needs_agent"}:status="completed"
        record_run(routine["id"],None,status,{"skill_id":skill_id,"skill_run_id":((result.get("run") or {}).get("id")),"event_id":(event or {}).get("id"),"trigger_type":routine.get("trigger_type","schedule"),"retried":retried});prefix="Retried once. " if retried else "";_push({"message":f"Routine “{routine['name']}” ran Skill {skill_id}. {prefix}{result.get('message','')}","card":result.get("card")})
    except Exception as exc:record_run(routine["id"],None,"failed",{"skill_id":skill_id,"event_id":(event or {}).get("id")});_push({"message":f"Routine “{routine['name']}” Skill execution failed: {exc}","card":None})
async def _execute_routine(routine:dict[str,Any],event:dict[str,Any]|None=None)->None:
    if routine.get("skill_id"):await _run_linked_skill(routine,event);return
    action=str(routine.get("instructions") or routine.get("action") or "");website=website_routine_target(action)
    if website:await _run_website_routine(routine,website,event);return
    instruction=_event_instruction(action,event);role=str(routine.get("agent_role") or "auto").strip().lower();owner=bool(routine.get("owner_agent_id"));job=create_job(_routine_session(routine),instruction,preferred_role=None if owner or role=="auto" else role);start_job(job["id"],_runner);record_run(routine["id"],job["id"],"started",{"event_id":(event or {}).get("id"),"trigger_type":routine.get("trigger_type","schedule")});owner_text=f" · {routine.get('owner_agent_name')}" if routine.get("owner_agent_name") else "";_push({"message":f"Routine started: {routine['name']}{owner_text}","card":{"type":"routine_run","routine_id":routine["id"],"routine_name":routine["name"],"owner_agent_id":routine.get("owner_agent_id"),"owner_agent_name":routine.get("owner_agent_name"),"event_id":(event or {}).get("id"),"job":job_card(job)}})
async def _dispatch_internal_events()->None:
    for event in pending_events(100):
        delivered={str(x) for x in event.get("delivered_routine_ids") or []};event_source=str((event.get("payload") or {}).get("source") or "")
        for routine in event_routines_for(event):
            rid=str(routine.get("id"))
            if rid in delivered or event_source==f"routine:{rid}":continue
            claimed=mark_event_routine_claimed(rid,datetime.now().astimezone()) or routine;await _execute_routine(claimed,event);mark_delivered(str(event["id"]),rid)
        close_event(str(event["id"]))
async def _loop()->None:
    while True:
        try:
            for routine in claim_due_routines(datetime.now().astimezone()):await _execute_routine(routine)
            await _dispatch_internal_events()
        except Exception as exc:_push({"message":f"Routine scheduler error: {exc}","card":None})
        await asyncio.sleep(15)
def start_routine_worker()->None:
    global _TASK
    if _TASK and not _TASK.done():return
    _TASK=asyncio.create_task(_loop())