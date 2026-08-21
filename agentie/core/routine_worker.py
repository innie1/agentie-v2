from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from agentie.core.browser_monitor import capture_website, routine_always_show, website_routine_target
from agentie.core.job_engine import create_job, job_card, poll_job_completion_events, start_job
from agentie.core.routine_engine import claim_due_routines, record_run
from agentie.core.runner import run_agent

WORKSPACE=Path.cwd()/"workspace"
EVENTS=WORKSPACE/"routine_events.json"
_TASK:asyncio.Task|None=None


def _load_events()->list[dict[str,Any]]:
    try:return json.loads(EVENTS.read_text(encoding="utf-8")) if EVENTS.exists() else []
    except Exception:return []
def _save_events(items:list[dict[str,Any]])->None:
    EVENTS.parent.mkdir(parents=True,exist_ok=True);EVENTS.write_text(json.dumps(items[-200:],indent=2,ensure_ascii=False),encoding="utf-8")
def _push(event:dict[str,Any])->None:
    items=_load_events();items.append(event);_save_events(items)
def poll_routine_events()->list[dict[str,Any]]:
    items=_load_events()
    if items:_save_events([])
    try:items.extend(poll_job_completion_events())
    except Exception:pass
    return items

async def _runner(instruction:str,specialist:str,session_id:str)->str:
    return await run_agent(instruction,specialist,session_id)

async def _run_website_routine(routine:dict[str,Any],url:str)->None:
    try:
        result=await capture_website(url,track_change=True)
        changed=bool(result.get("changed"));first=bool(result.get("first_check"));always=routine_always_show(str(routine.get("action") or ""))
        status="changed" if changed else "unchanged"
        record_run(routine["id"],None,status)
        if first or changed or always:
            prefix=f"Website routine: {routine['name']}"
            _push({"message":f"{prefix}. {result.get('message','')}","card":result.get("card")})
    except Exception as exc:
        record_run(routine["id"],None,"failed")
        _push({"message":f"Website routine “{routine['name']}” failed: {exc}","card":None})

async def _loop()->None:
    while True:
        try:
            for routine in claim_due_routines(datetime.now().astimezone()):
                action=str(routine.get("action") or "")
                website=website_routine_target(action)
                if website:
                    await _run_website_routine(routine,website)
                    continue
                role=str(routine.get("agent_role") or "auto").strip().lower()
                job=create_job(f"routine:{routine['id']}",routine["action"],preferred_role=None if role=="auto" else role)
                start_job(job["id"],_runner);record_run(routine["id"],job["id"],"started")
                _push({"message":f"Routine started: {routine['name']}","card":{"type":"routine_run","routine_id":routine["id"],"routine_name":routine["name"],"job":job_card(job)}})
        except Exception as exc:
            _push({"message":f"Routine scheduler error: {exc}","card":None})
        await asyncio.sleep(15)

def start_routine_worker()->None:
    global _TASK
    if _TASK and not _TASK.done():return
    _TASK=asyncio.create_task(_loop())
