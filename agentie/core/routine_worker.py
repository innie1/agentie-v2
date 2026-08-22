from __future__ import annotations

import asyncio,json
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
    owner=str(routine.get("owner_agent_id") or "").strip()
    return f"agent:{owner}:routine:{routine['id']}" if owner else f"routine:{routine['id']}"
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
async def _run_linked_skill(routine:dict[str,Any],event:dict[str,Any]|None=None)->None:
    skill_id=str(routine.get("skill_id") or "").strip()
    if not skill_id:return
    if not routine.get("owner_agent_id"):
        record_run(routine["id"],None,"failed",{"skill_id":skill_id,"event_id":(event or {}).get("id")});_push({"message":f"Routine “{routine['name']}” cannot run Skill {skill_id} until it has an owner agent.","card":None});return
    try:
        from agentie.core.workflow_skills import get_workflow_skill
        skill=get_workflow_skill(skill_id)
        if not skill:raise ValueError(f"Skill {skill_id} was not found.")
        payload=dict((event or {}).get("payload") or {});inputs={str(k):v for k,v in payload.items() if isinstance(v,(str,int,float,bool))};session=_routine_session(routine)
        if skill.get("source_workflow_id"):
            from agentie.core.workflow_browser_runtime import _run_skill
            invocation=skill_id
            if inputs:invocation += " with inputs " + ", ".join(f"{k}={v}" for k,v in inputs.items())
            result=await _run_skill(invocation,session);status=_browser_skill_status(result)
        else:
            from agentie.core.workflow_skill_runtime import execute_workflow_skill
            result=await execute_workflow_skill(skill_id,session,inputs=inputs,requested_by="routine",source=f"routine:{routine['id']}");status=str(result.get("status") or "completed")
        if status not in {"completed","failed","awaiting_approval","needs_input","needs_access","inactive","needs_agent"}:status="completed"
        record_run(routine["id"],None,status,{"skill_id":skill_id,"skill_run_id":((result.get("run") or {}).get("id")),"event_id":(event or {}).get("id"),"trigger_type":routine.get("trigger_type","schedule")});_push({"message":f"Routine “{routine['name']}” ran Skill {skill_id}. {result.get('message','')}","card":result.get("card")})
    except Exception as exc:record_run(routine["id"],None,"failed",{"skill_id":skill_id,"event_id":(event or {}).get("id")});_push({"message":f"Routine “{routine['name']}” Skill execution failed: {exc}","card":None})
async def _execute_routine(routine:dict[str,Any],event:dict[str,Any]|None=None)->None:
    if routine.get("skill_id"):
        await _run_linked_skill(routine,event);return
    action=str(routine.get("instructions") or routine.get("action") or "");website=website_routine_target(action)
    if website:
        await _run_website_routine(routine,website,event);return
    role=str(routine.get("agent_role") or "auto").strip().lower();owner=bool(routine.get("owner_agent_id"));job=create_job(_routine_session(routine),action,preferred_role=None if owner or role=="auto" else role);start_job(job["id"],_runner);record_run(routine["id"],job["id"],"started",{"event_id":(event or {}).get("id"),"trigger_type":routine.get("trigger_type","schedule")});owner_text=f" · {routine.get('owner_agent_name')}" if routine.get("owner_agent_name") else "";_push({"message":f"Routine started: {routine['name']}{owner_text}","card":{"type":"routine_run","routine_id":routine["id"],"routine_name":routine["name"],"owner_agent_id":routine.get("owner_agent_id"),"owner_agent_name":routine.get("owner_agent_name"),"event_id":(event or {}).get("id"),"job":job_card(job)}})
async def _dispatch_internal_events()->None:
    for event in pending_events(100):
        delivered={str(x) for x in event.get("delivered_routine_ids") or []}
        for routine in event_routines_for(event):
            if str(routine.get("id")) in delivered:continue
            claimed=mark_event_routine_claimed(str(routine["id"]),datetime.now().astimezone()) or routine
            await _execute_routine(claimed,event);mark_delivered(str(event["id"]),str(routine["id"]))
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
