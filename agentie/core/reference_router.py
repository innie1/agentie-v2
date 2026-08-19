import json
import re
from datetime import datetime, timedelta
from typing import Any

from agentie.core.memory_store import get_context, set_context
from agentie.tools import local_utility_tools as local_utils
from agentie.tools import productivity_tools as productivity

_DURATION_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(seconds?|secs?|sec|s|minutes?|mins?|min|m|hours?|hrs?|hr|h)\b", re.I)
_JOB_SIGNAL_RE = re.compile(r"\b(delegate|research|investigate|compare|analy[sz]e|build|implement|debug|refactor|github|repository|report|deep search|multi[- ]?step|parallel)\b", re.I)
_JOBS_RESUMED = False


def _seconds(match: re.Match[str]) -> float:
    value = float(match.group(1)); unit = match.group(2).lower()
    if unit.startswith("h"): return value * 3600
    if unit.startswith("m"): return value * 60
    return value


def _load_reminders() -> list[dict]:
    try: return json.loads(productivity.REMINDERS.read_text(encoding="utf-8")) if productivity.REMINDERS.exists() else []
    except Exception: return []


def _job_runner_session(session_id: str, job_id: str, specialist: str) -> str:
    return f"{session_id}:job:{job_id}:{specialist}"


async def _job_step_runner(instruction: str, specialist: str, session_id: str) -> str:
    from agentie.core.runner import run_agent
    active = get_context(session_id, "active_job_id", "job")
    return await run_agent(instruction, specialist, _job_runner_session(session_id, str(active), specialist))


def _ensure_jobs_resumed() -> None:
    global _JOBS_RESUMED
    if _JOBS_RESUMED: return
    _JOBS_RESUMED = True
    try:
        from agentie.core.job_engine import resume_unfinished
        resume_unfinished(_job_step_runner)
    except RuntimeError:
        _JOBS_RESUMED = False
    except Exception:
        pass


def _looks_like_background_job(message: str) -> bool:
    text = re.sub(r"\s+", " ", message.strip()); lower = text.lower()
    local_hits = len(re.findall(r"\b(timer|alarm|remind|time|weather|calculate|convert|note|system status|stopwatch)\b", lower))
    complex_hits = len(_JOB_SIGNAL_RE.findall(lower))
    if re.search(r"\b(delegate|deep search|run (?:this )?as a job|background job|parallel agents?)\b", lower): return True
    if local_hits >= 2 and complex_hits == 0: return False
    return complex_hits >= 2 or (complex_hits >= 1 and len(text) >= 180)


def remember_active_from_card(session_id: str, card: dict[str, Any] | None) -> None:
    if not isinstance(card, dict): return
    if card.get("type") == "multi":
        for item in reversed(card.get("items") or []):
            child = item.get("card") if isinstance(item, dict) else None
            if isinstance(child, dict):
                remember_active_from_card(session_id, child)
                if get_context(session_id, "active_object"): return
        return
    card_type = str(card.get("type") or "")
    if card_type in {"timer", "alarm", "reminder", "schedule", "uploaded_file", "note", "task", "tasks", "job_progress"}:
        set_context(session_id, "active_object", {"type": card_type, "card": card})
        if card_type == "job_progress" and card.get("id"): set_context(session_id, "active_job_id", str(card["id"]))


def _job_command(session_id: str, message: str) -> dict[str, Any] | None:
    from agentie.core.job_engine import cancel_job, create_job, get_job, job_card, job_events, start_job
    text = re.sub(r"\s+", " ", message.strip()); lower = text.lower().strip(" .?!"); active_id = str(get_context(session_id, "active_job_id", "") or "")
    status = re.match(r"^(?:show |check )?(?:job )?(?:status|progress)(?: (?:for|of))?\s*([a-f0-9]{6,12})?$", lower)
    if status:
        job_id = status.group(1) or active_id
        if not job_id: return {"message":"Which job should I check?","card":None,"routed_by":"job"}
        try: job=get_job(job_id)
        except KeyError: return {"message":"I couldn't find that job.","card":None,"routed_by":"job"}
        set_context(session_id,"active_job_id",job_id); return {"message":f"Job {job_id}: {job['status']}.","card":job_card(job),"routed_by":"job"}
    cancel = re.match(r"^(?:cancel|stop)\s+(?:the\s+)?job(?:\s+([a-f0-9]{6,12}))?$", lower)
    if cancel:
        job_id=cancel.group(1) or active_id
        if not job_id:return {"message":"Which job should I cancel?","card":None,"routed_by":"job"}
        try:job=cancel_job(job_id)
        except KeyError:return {"message":"I couldn't find that job.","card":None,"routed_by":"job"}
        return {"message":f"Job {job_id} cancelled.","card":job_card(job),"routed_by":"job"}
    trace = re.match(r"^(?:show )?(?:job )?trace(?:\s+([a-f0-9]{6,12}))?$", lower)
    if trace:
        job_id=trace.group(1) or active_id
        if not job_id:return {"message":"Which job trace should I show?","card":None,"routed_by":"job"}
        try:events=job_events(job_id)
        except Exception:return {"message":"I couldn't read that job trace.","card":None,"routed_by":"job"}
        return {"message":f"Trace for job {job_id}.","card":{"type":"job_trace","id":job_id,"events":events},"routed_by":"job"}
    explicit = re.match(r"^(?:delegate|start (?:a )?(?:background )?job(?: to)?|run (?:this )?as a job)\s*[:\-]?\s*(.+)$", text, re.I)
    goal=explicit.group(1).strip() if explicit else text
    if explicit or _looks_like_background_job(text):
        job=create_job(session_id,goal); set_context(session_id,"active_job_id",job["id"]); start_job(job["id"],_job_step_runner); card=job_card(job); set_context(session_id,"active_object",{"type":"job_progress","card":card})
        return {"message":f"Started job {job['id']} with {job['total_steps']} planned step(s). You can keep chatting while it runs.","card":card,"routed_by":"job"}
    return None


def try_active_reference(session_id: str, message: str) -> dict[str, Any] | None:
    _ensure_jobs_resumed()
    job_result=_job_command(session_id,message)
    if job_result is not None:return job_result
    active=get_context(session_id,"active_object")
    if not isinstance(active,dict):return None
    card=active.get("card") if isinstance(active.get("card"),dict) else {}; object_type=str(active.get("type") or card.get("type") or ""); text=re.sub(r"\s+"," ",message.lower().strip()); duration=_DURATION_RE.search(text); change_words=bool(re.search(r"\b(?:make|change|set|restart|reset|instead|again)\b",text)); add_words=bool(re.search(r"\b(?:add|plus|increase|extend)\b",text)); reference_words=bool(re.search(r"\b(?:it|that|this|timer|alarm|reminder)\b",text))
    if object_type in {"timer","alarm"}:
        timer_id=str(card.get("id") or "")
        if not timer_id:return None
        if duration and reference_words and (change_words or add_words):
            requested=_seconds(duration)
            if add_words:
                try:due=datetime.fromisoformat(str(card.get("due_at")));now=datetime.now(due.tzinfo) if due.tzinfo else datetime.now();current=max(0.0,(due-now).total_seconds())
                except Exception:current=float(card.get("duration_seconds") or 0)
                requested+=current
            refreshed=local_utils._restart_timer(timer_id,requested)
            if not refreshed:return None
            new_card=dict(card);new_card.update({"type":object_type,"id":timer_id,"status":refreshed.get("status","running"),"duration_seconds":requested,"due_at":refreshed.get("due_at")});set_context(session_id,"active_object",{"type":object_type,"card":new_card});pretty=int(requested) if float(requested).is_integer() else round(requested,1)
            return {"message":f"{'Timer' if object_type=='timer' else 'Alarm'} updated to {pretty} seconds from now.","card":new_card,"routed_by":"active_reference"}
        if reference_words and re.search(r"\b(?:cancel|stop|dismiss)\b",text):
            with local_utils._TIMER_LOCK:
                item=local_utils._TIMERS.get(timer_id)
                if not item:return None
                item["status"]="cancelled"
            new_card=dict(card);new_card["status"]="cancelled";set_context(session_id,"active_object",{"type":object_type,"card":new_card});return {"message":f"{'Timer' if object_type=='timer' else 'Alarm'} cancelled.","card":new_card,"routed_by":"active_reference"}
    if object_type=="reminder":
        reminder_id=str(card.get("id") or "")
        if not reminder_id:return None
        if duration and reference_words and (change_words or add_words):
            seconds=_seconds(duration);items=_load_reminders();target=next((x for x in items if str(x.get("id"))==reminder_id),None)
            if target is None:return None
            try:old_due=datetime.fromisoformat(str(target.get("due_at")));now=datetime.now(old_due.tzinfo) if old_due.tzinfo else datetime.now()
            except Exception:now=datetime.now();old_due=now
            new_due=old_due+timedelta(seconds=seconds) if add_words else now+timedelta(seconds=seconds);target["due_at"]=new_due.isoformat(timespec="seconds");target["status"]="scheduled";productivity._save(productivity.REMINDERS,items);new_card={"type":"reminder",**target};set_context(session_id,"active_object",{"type":"reminder","card":new_card});return {"message":f"Updated that reminder for {new_due.strftime('%H:%M:%S')}.","card":new_card,"routed_by":"active_reference"}
        if reference_words and re.search(r"\b(?:cancel|delete|remove|dismiss)\b",text):
            items=_load_reminders();target=next((x for x in items if str(x.get("id"))==reminder_id),None)
            if target is None:return None
            target["status"]="cancelled";productivity._save(productivity.REMINDERS,items);new_card={"type":"reminder",**target};set_context(session_id,"active_object",{"type":"reminder","card":new_card});return {"message":"Reminder cancelled.","card":new_card,"routed_by":"active_reference"}
    return None
