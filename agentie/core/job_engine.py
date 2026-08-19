import asyncio
import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

WORKSPACE = Path.cwd() / "workspace"
DB_PATH = WORKSPACE / "agentie_jobs.sqlite3"
_LOCK = threading.Lock()
_RUNNING: dict[str, asyncio.Task] = {}
StepRunner = Callable[[str, str, str], Awaitable[str]]


def _now() -> str: return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _connect() -> sqlite3.Connection:
    WORKSPACE.mkdir(parents=True, exist_ok=True); conn=sqlite3.connect(DB_PATH, timeout=10); conn.row_factory=sqlite3.Row; conn.execute("PRAGMA journal_mode=WAL"); return conn

def init_db() -> None:
    with _LOCK, _connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,goal TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,final_output TEXT,error TEXT,provider_calls INTEGER NOT NULL DEFAULT 0,budget_provider_calls INTEGER NOT NULL DEFAULT 8);
        CREATE TABLE IF NOT EXISTS job_steps(job_id TEXT NOT NULL,id TEXT NOT NULL,position INTEGER NOT NULL,title TEXT NOT NULL,instruction TEXT NOT NULL,specialist TEXT NOT NULL,status TEXT NOT NULL,depends_on_json TEXT NOT NULL,output TEXT,error TEXT,attempts INTEGER NOT NULL DEFAULT 0,started_at TEXT,finished_at TEXT,PRIMARY KEY(job_id,id));
        CREATE INDEX IF NOT EXISTS idx_job_steps_job ON job_steps(job_id,position);
        CREATE TABLE IF NOT EXISTS job_events(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL,kind TEXT NOT NULL,message TEXT NOT NULL,metadata_json TEXT,created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_job_events_job ON job_events(job_id,id);
        """)

def _event(job_id:str,kind:str,message:str,metadata:dict[str,Any]|None=None)->None:
    with _LOCK,_connect() as conn: conn.execute("INSERT INTO job_events(job_id,kind,message,metadata_json,created_at) VALUES(?,?,?,?,?)",(job_id,kind,message,json.dumps(metadata or {},ensure_ascii=False),_now()))

def _specialist(text:str)->str:
    lower=text.lower()
    if re.search(r"\b(github|repository|repo|pull request|issue|commit|branch)\b",lower): return "github"
    if re.search(r"\b(code|coding|python|javascript|typescript|bug|debug|implement|refactor|test|file|pdf|csv|json|yaml|zip)\b",lower): return "coding"
    if re.search(r"\b(research|search|web|latest|sources?|compare|investigate|find out|news)\b",lower): return "research"
    return "general"

def make_plan(goal:str)->list[dict[str,Any]]:
    cleaned=re.sub(r"\s+"," ",goal.strip()); lower=cleaned.lower(); steps=[]
    researchish=bool(re.search(r"\b(research|search|latest|compare|investigate|sources?|web)\b",lower)); synthesis=bool(re.search(r"\b(report|summary|summarize|write|draft|document|pdf|presentation)\b",lower)); codingish=bool(re.search(r"\b(code|build|implement|fix|debug|refactor|test)\b",lower))
    if researchish and synthesis:
        return [{"id":"s1","title":"Research","instruction":f"Research this goal carefully and return source-grounded findings: {cleaned}","specialist":"research","depends_on":[]},{"id":"s2","title":"Synthesize","instruction":f"Using the completed research, produce the requested final deliverable for: {cleaned}","specialist":"general","depends_on":["s1"]}]
    if codingish and re.search(r"\b(test|verify|check)\b",lower):
        return [{"id":"s1","title":"Implement","instruction":cleaned,"specialist":"coding","depends_on":[]},{"id":"s2","title":"Verify","instruction":"Verify the implementation, run appropriate checks, and report failures clearly.","specialist":"coding","depends_on":["s1"]}]
    sequential=bool(re.search(r"\bthen\b",cleaned,re.I)); clauses=[x.strip(" .") for x in re.split(r"\s*(?:;|\bthen\b|\band then\b)\s*",cleaned,flags=re.I) if x.strip(" .")]
    if len(clauses)==1:
        parts=re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+",cleaned,flags=re.I); action=re.compile(r"^(?:research|search|find|compare|analyze|analyse|write|create|build|fix|test|inspect|read|summarize|summarise|check|look|calculate|convert|show)\b",re.I)
        if len(parts)>1 and sum(bool(action.search(p.strip())) for p in parts)>=2: clauses=[p.strip(" .") for p in parts if p.strip(" .")]
    previous=None
    for idx,clause in enumerate(clauses[:8],1):
        sid=f"s{idx}"; steps.append({"id":sid,"title":clause[:64],"instruction":clause,"specialist":_specialist(clause),"depends_on":[previous] if sequential and previous else []}); previous=sid
    return steps or [{"id":"s1","title":"Complete goal","instruction":cleaned,"specialist":_specialist(cleaned),"depends_on":[]}]

def create_job(session_id:str,goal:str,budget_provider_calls:int=8)->dict[str,Any]:
    init_db(); job_id=uuid.uuid4().hex[:10]; now=_now(); plan=make_plan(goal); budget=max(0,min(int(budget_provider_calls),50))
    with _LOCK,_connect() as conn:
        conn.execute("INSERT INTO jobs(id,session_id,goal,status,created_at,updated_at,budget_provider_calls) VALUES(?,?,?,?,?,?,?)",(job_id,session_id,goal,"queued",now,now,budget))
        for pos,s in enumerate(plan): conn.execute("INSERT INTO job_steps(job_id,id,position,title,instruction,specialist,status,depends_on_json) VALUES(?,?,?,?,?,?,?,?)",(job_id,s["id"],pos,s["title"],s["instruction"],s["specialist"],"queued",json.dumps(s.get("depends_on",[]))))
    _event(job_id,"plan",f"Created plan with {len(plan)} step(s).",{"steps":plan}); return get_job(job_id)

def get_job(job_id:str)->dict[str,Any]:
    init_db()
    with _LOCK,_connect() as conn:
        job=conn.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone(); rows=conn.execute("SELECT * FROM job_steps WHERE job_id=? ORDER BY position",(job_id,)).fetchall() if job else []
    if not job: raise KeyError(job_id)
    steps=[]
    for r in rows:
        item=dict(r); item["depends_on"]=json.loads(item.pop("depends_on_json") or "[]"); steps.append(item)
    data=dict(job); data["steps"]=steps; data["completed_steps"]=sum(s["status"]=="completed" for s in steps); data["total_steps"]=len(steps); return data

def list_jobs(session_id:str|None=None,limit:int=30)->list[dict[str,Any]]:
    init_db()
    with _LOCK,_connect() as conn:
        rows=conn.execute("SELECT id FROM jobs WHERE session_id=? ORDER BY created_at DESC LIMIT ?",(session_id,limit)).fetchall() if session_id else conn.execute("SELECT id FROM jobs ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall()
    return [get_job(str(r["id"])) for r in rows]

def job_events(job_id:str,limit:int=100)->list[dict[str,Any]]:
    init_db()
    with _LOCK,_connect() as conn: rows=conn.execute("SELECT * FROM job_events WHERE job_id=? ORDER BY id DESC LIMIT ?",(job_id,limit)).fetchall()
    out=[]
    for r in reversed(rows): item=dict(r); item["metadata"]=json.loads(item.pop("metadata_json") or "{}"); out.append(item)
    return out

def _set_job(job_id:str,**fields:Any)->None:
    if not fields:return
    fields["updated_at"]=_now(); sql=",".join(f"{k}=?" for k in fields)
    with _LOCK,_connect() as conn: conn.execute(f"UPDATE jobs SET {sql} WHERE id=?",(*fields.values(),job_id))

def _set_step(job_id:str,step_id:str,**fields:Any)->None:
    if not fields:return
    sql=",".join(f"{k}=?" for k in fields)
    with _LOCK,_connect() as conn: conn.execute(f"UPDATE job_steps SET {sql} WHERE job_id=? AND id=?",(*fields.values(),job_id,step_id))
    _set_job(job_id)

def _reserve_agent_call(job_id:str)->bool:
    with _LOCK,_connect() as conn:
        row=conn.execute("SELECT provider_calls,budget_provider_calls FROM jobs WHERE id=?",(job_id,)).fetchone()
        if not row or int(row["provider_calls"])>=int(row["budget_provider_calls"]): return False
        conn.execute("UPDATE jobs SET provider_calls=provider_calls+1,updated_at=? WHERE id=?",(_now(),job_id)); return True

def cancel_job(job_id:str)->dict[str,Any]:
    job=get_job(job_id)
    if job["status"] in {"completed","failed","cancelled"}:return job
    _set_job(job_id,status="cancelled")
    with _LOCK,_connect() as conn: conn.execute("UPDATE job_steps SET status='cancelled' WHERE job_id=? AND status IN ('queued','running')",(job_id,))
    task=_RUNNING.get(job_id)
    if task and not task.done():task.cancel()
    _event(job_id,"cancel","Job cancelled by user."); return get_job(job_id)

async def _run_one(job_id:str,step:dict[str,Any],runner:StepRunner)->None:
    if not _reserve_agent_call(job_id):
        _set_step(job_id,step["id"],status="failed",error="Agent-call budget exhausted",finished_at=_now()); _event(job_id,"budget","Agent-call budget exhausted.",{"step_id":step["id"]}); return
    _set_step(job_id,step["id"],status="running",started_at=_now(),attempts=int(step.get("attempts") or 0)+1); _event(job_id,"step_started",f"{step['specialist']} started: {step['title']}",{"step_id":step["id"],"specialist":step["specialist"]})
    job=get_job(job_id); by_id={s["id"]:s for s in job["steps"]}; deps=[f"Output from {d}:\n{by_id[d]['output']}" for d in step.get("depends_on",[]) if d in by_id and by_id[d].get("output")]; instruction=step["instruction"]+("\n\nUse these completed dependency outputs:\n"+"\n\n".join(deps) if deps else "")
    try:
        output=await runner(instruction,step["specialist"],job["session_id"]); _set_step(job_id,step["id"],status="completed",output=output,error=None,finished_at=_now()); _event(job_id,"step_completed",f"Completed: {step['title']}",{"step_id":step["id"]})
    except asyncio.CancelledError: _set_step(job_id,step["id"],status="cancelled",finished_at=_now()); raise
    except Exception as exc: _set_step(job_id,step["id"],status="failed",error=str(exc),finished_at=_now()); _event(job_id,"step_failed",f"Failed: {step['title']}: {exc}",{"step_id":step["id"]})

async def execute_job(job_id:str,runner:StepRunner)->None:
    try:
        _set_job(job_id,status="running",error=None); _event(job_id,"job_started","Job execution started.")
        while True:
            job=get_job(job_id)
            if job["status"]=="cancelled":return
            steps=job["steps"]; pending=[s for s in steps if s["status"]=="queued"]
            if not pending:break
            completed={s["id"] for s in steps if s["status"]=="completed"}; failed={s["id"] for s in steps if s["status"] in {"failed","cancelled"}}; runnable=[s for s in pending if set(s.get("depends_on",[]))<=completed]; blocked=[s for s in pending if set(s.get("depends_on",[]))&failed]
            for s in blocked:_set_step(job_id,s["id"],status="failed",error="Dependency failed",finished_at=_now())
            if not runnable:
                if blocked:continue
                _set_job(job_id,status="failed",error="No runnable steps; dependency cycle or missing dependency.");_event(job_id,"job_failed","No runnable steps.");return
            await asyncio.gather(*[_run_one(job_id,s,runner) for s in runnable])
        job=get_job(job_id); failed_steps=[s for s in job["steps"] if s["status"]=="failed"]; outputs=[s["output"] for s in job["steps"] if s.get("output")]
        if failed_steps:_set_job(job_id,status="failed",final_output="\n\n".join(outputs),error=f"{len(failed_steps)} step(s) failed");_event(job_id,"job_failed",f"Job finished with {len(failed_steps)} failed step(s).")
        else:_set_job(job_id,status="completed",final_output=(outputs[-1] if len(outputs)==1 else "\n\n---\n\n".join(outputs)),error=None);_event(job_id,"job_completed","Job completed successfully.")
    except asyncio.CancelledError:_set_job(job_id,status="cancelled")
    except Exception as exc:_set_job(job_id,status="failed",error=str(exc));_event(job_id,"job_failed",str(exc))
    finally:_RUNNING.pop(job_id,None)

def start_job(job_id:str,runner:StepRunner)->None:
    existing=_RUNNING.get(job_id)
    if existing and not existing.done():return
    _RUNNING[job_id]=asyncio.create_task(execute_job(job_id,runner))

def resume_unfinished(runner:StepRunner)->int:
    init_db()
    with _LOCK,_connect() as conn:
        rows=conn.execute("SELECT id FROM jobs WHERE status IN ('queued','running') ORDER BY created_at").fetchall(); conn.execute("UPDATE job_steps SET status='queued',started_at=NULL WHERE status='running'")
    for r in rows:start_job(str(r["id"]),runner)
    return len(rows)

def job_card(job:dict[str,Any])->dict[str,Any]:
    return {"type":"job_progress","id":job["id"],"goal":job["goal"],"status":job["status"],"completed_steps":job.get("completed_steps",0),"total_steps":job.get("total_steps",0),"provider_calls":job.get("provider_calls",0),"budget_provider_calls":job.get("budget_provider_calls",0),"final_output":job.get("final_output"),"error":job.get("error"),"steps":[{"id":s["id"],"title":s["title"],"specialist":s["specialist"],"status":s["status"],"attempts":s["attempts"],"error":s.get("error")} for s in job.get("steps",[])]}
