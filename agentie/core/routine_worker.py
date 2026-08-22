from __future__ import annotations

import asyncio,json
from datetime import datetime
from pathlib import Path
from typing import Any

from agentie.core.browser_monitor import capture_website,routine_always_show,website_routine_target
from agentie.core.job_engine import create_job,job_card,poll_job_completion_events,start_job
from agentie.core.routine_engine import claim_due_routines,record_run
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
async def _run_website_routine(routine:dict[str,Any],url:str)->None:
    try:
        result=await capture_website(url,track_change=True);changed=bool(result.get("changed"));first=bool(result.get("first_check"));always=routine_always_show(str(routine.get("action") or ""));status="changed" if changed else "unchanged";record_run(routine["id"],None,status)
        if first or changed or always:_push({"message":f"Website routine: {routine['name']}. {result.get('message','')}","card":result.get("card")})
    except Exception as exc:record_run(routine["id"],None,"failed");_push({"message":f"Website routine “{routine['name']}” failed: {exc}","card":None})
def _routine_session(routine:dict[str,Any])->str:
    owner=str(routine.get("owner_agent_id") or "").strip()
    return f"agent:{owner}:routine:{routine['id']}" if owner else f"routine:{routine['id']}"
async def _loop()->None:
    while True:
        try:
            for routine in claim_due_routines(datetime.now().astimezone()):
                action=str(routine.get("instructions") or routine.get("action") or "");website=website_routine_target(action)
                if website:
                    await _run_website_routine(routine,website);continue
                # Owner identity is now first-class. Legacy role-owned routines
                # still use preferred_role until the user edits/reassigns them.
                role=str(routine.get("agent_role") or "auto").strip().lower();owner=bool(routine.get("owner_agent_id"));job=create_job(_routine_session(routine),action,preferred_role=None if owner or role=="auto" else role);start_job(job["id"],_runner);record_run(routine["id"],job["id"],"started");owner_text=f" · {routine.get('owner_agent_name')}" if routine.get("owner_agent_name") else "";_push({"message":f"Routine started: {routine['name']}{owner_text}","card":{"type":"routine_run","routine_id":routine["id"],"routine_name":routine["name"],"owner_agent_id":routine.get("owner_agent_id"),"owner_agent_name":routine.get("owner_agent_name"),"job":job_card(job)}})
        except Exception as exc:_push({"message":f"Routine scheduler error: {exc}","card":None})
        await asyncio.sleep(15)
def start_routine_worker()->None:
    global _TASK
    if _TASK and not _TASK.done():return
    _TASK=asyncio.create_task(_loop())
