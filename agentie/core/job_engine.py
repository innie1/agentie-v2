import asyncio
import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

WORKSPACE=Path.cwd()/"workspace"
DB_PATH=WORKSPACE/"agentie_jobs.sqlite3"
_LOCK=threading.Lock();_RUNNING:dict[str,asyncio.Task]={}
StepRunner=Callable[[str,str,str],Awaitable[str]]

def _now():return datetime.now(timezone.utc).isoformat(timespec="seconds")
def _connect():
    WORKSPACE.mkdir(parents=True,exist_ok=True);c=sqlite3.connect(DB_PATH,timeout=10);c.row_factory=sqlite3.Row;c.execute("PRAGMA journal_mode=WAL");return c
def init_db():
    with _LOCK,_connect() as c:c.executescript("""
    CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,goal TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,final_output TEXT,error TEXT,provider_calls INTEGER NOT NULL DEFAULT 0,budget_provider_calls INTEGER NOT NULL DEFAULT 8);
    CREATE TABLE IF NOT EXISTS job_steps(job_id TEXT NOT NULL,id TEXT NOT NULL,position INTEGER NOT NULL,title TEXT NOT NULL,instruction TEXT NOT NULL,specialist TEXT NOT NULL,status TEXT NOT NULL,depends_on_json TEXT NOT NULL,output TEXT,error TEXT,attempts INTEGER NOT NULL DEFAULT 0,started_at TEXT,finished_at TEXT,PRIMARY KEY(job_id,id));
    CREATE TABLE IF NOT EXISTS job_events(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL,kind TEXT NOT NULL,message TEXT NOT NULL,metadata_json TEXT,created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_job_steps_job ON job_steps(job_id,position);CREATE INDEX IF NOT EXISTS idx_job_events_job ON job_events(job_id,id);
    """)
def _event(j,k,m,meta=None):
    with _LOCK,_connect() as c:c.execute("INSERT INTO job_events(job_id,kind,message,metadata_json,created_at) VALUES(?,?,?,?,?)",(j,k,m,json.dumps(meta or {},ensure_ascii=False),_now()))
def _specialist(t):
    x=t.lower()
    if re.search(r"\b(github|repository|repo|pull request|issue|commit|branch)\b",x):return "github"
    if re.search(r"\b(code|coding|python|javascript|typescript|bug|debug|implement|refactor|test|file|pdf|csv|json|yaml|zip)\b",x):return "coding"
    if re.search(r"\b(research|search|web|latest|sources?|compare|investigate|find out|news)\b",x):return "research"
    return "general"
def make_plan(goal):
    clean=re.sub(r"\s+"," ",goal.strip());low=clean.lower();research=bool(re.search(r"\b(research|search|latest|compare|investigate|sources?|web|deep research|deep search|deeper search)\b",low));synthesis=bool(re.search(r"\b(report|summary|summarize|write|draft|document|pdf|presentation|research)\b",low))
    if research and (synthesis or "deep search" in low or "deeper search" in low):return [{"id":"s1","title":"Deep research","instruction":clean,"specialist":"deep_research","depends_on":[]}]
    if coding and re.search(r"\b(test|verify|check)\b",low):return [{"id":"s1","title":"Implement","instruction":clean,"specialist":"coding","depends_on":[]},{"id":"s2","title":"Verify","instruction":"Verify the implementation, run appropriate checks, and report failures clearly.","specialist":"coding","depends_on":["s1"]}]
    sequential=bool(re.search(r"\bthen\b",clean,re.I));clauses=[x.strip(" .") for x in re.split(r"\s*(?:;|\bthen\b|\band then\b)\s*",clean,flags=re.I) if x.strip(" .")]
    if len(clauses)==1:
        parts=re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+",clean,flags=re.I);action=re.compile(r"^(?:research|search|find|compare|analyze|analyse|write|create|build|fix|test|inspect|read|summarize|summarise|check|look|calculate|convert|show)\b",re.I)
        if len(parts)>1 and sum(bool(action.search(p.strip())) for p in parts)>=2:clauses=[p.strip(" .") for p in parts if p.strip(" .")]
    out=[];prev=None
    for i,clause in enumerate(clauses[:8],1):
        sid=f"s{i}";out.append({"id":sid,"title":clause[:64],"instruction":clause,"specialist":_specialist(clause),"depends_on":[prev] if sequential and prev else []});prev=sid
    return out or [{"id":"s1","title":"Complete goal","instruction":clean,"specialist":_specialist(clean),"depends_on":[]}]
def create_job(session_id,goal,budget_provider_calls=8,preferred_role=None):
    init_db();jid=uuid.uuid4().hex[:10];now=_now();plan=make_plan(goal);budget=max(0,min(int(budget_provider_calls),50));preferred=str(preferred_role or "").strip().lower()
    if preferred:
        for step in plan:
            if step["specialist"]!="deep_research":step["specialist"]=preferred
    with _LOCK,_connect() as c:
        c.execute("INSERT INTO jobs(id,session_id,goal,status,created_at,updated_at,budget_provider_calls) VALUES(?,?,?,?,?,?,?)",(jid,session_id,goal,"queued",now,now,budget))
        for pos,s in enumerate(plan):c.execute("INSERT INTO job_steps(job_id,id,position,title,instruction,specialist,status,depends_on_json) VALUES(?,?,?,?,?,?,?,?)",(jid,s["id"],pos,s["title"],s["instruction"],s["specialist"],"queued",json.dumps(s.get("depends_on",[]))))
    _event(jid,"plan",f"Created plan with {len(plan)} step(s).",{"steps":plan,"preferred_role":preferred or None});return get_job(jid)
def get_job(jid):
    init_db()
    with _LOCK,_connect() as c:j=c.execute("SELECT * FROM jobs WHERE id=?",(jid,)).fetchone();rows=c.execute("SELECT * FROM job_steps WHERE job_id=? ORDER BY position",(jid,)).fetchall() if j else []
    if not j:raise KeyError(jid)
    steps=[]
    for r in rows:i=dict(r);i["depends_on"]=json.loads(i.pop("depends_on_json") or "[]");steps.append(i)
    d=dict(j);d["steps"]=steps;d["completed_steps"]=sum(s["status"]=="completed" for s in steps);d["total_steps"]=len(steps);return d
def list_jobs(session_id=None,limit=30):
    init_db()
    with _LOCK,_connect() as c:rows=c.execute("SELECT id FROM jobs WHERE session_id=? ORDER BY created_at DESC LIMIT ?",(session_id,limit)).fetchall() if session_id else c.execute("SELECT id FROM jobs ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall()
    return [get_job(str(r["id"])) for r in rows]
def job_events(jid,limit=100):
    init_db()
    with _LOCK,_connect() as c:rows=c.execute("SELECT * FROM job_events WHERE job_id=? ORDER BY id DESC LIMIT ?",(jid,limit)).fetchall()
    out=[]
    for r in reversed(rows):i=dict(r);i["metadata"]=json.loads(i.pop("metadata_json") or "{}");out.append(i)
    return out
def _set_job(jid,**f):
    if not f:return
    f["updated_at"]=_now();sql=",".join(f"{k}=?" for k in f)
    with _LOCK,_connect() as c:c.execute(f"UPDATE jobs SET {sql} WHERE id=?",(*f.values(),jid))
def _set_step(jid,sid,**f):
    if not f:return
    sql=",".join(f"{k}=?" for k in f)
    with _LOCK,_connect() as c:c.execute(f"UPDATE job_steps SET {sql} WHERE job_id=? AND id=?",(*f.values(),jid,sid))
    _set_job(jid)
def _reserve(jid):
    with _LOCK,_connect() as c:
        r=c.execute("SELECT provider_calls,budget_provider_calls FROM jobs WHERE id=?",(jid,)).fetchone()
        if not r or int(r["provider_calls"])>=int(r["budget_provider_calls"]):return False
        c.execute("UPDATE jobs SET provider_calls=provider_calls+1,updated_at=? WHERE id=?",(_now(),jid));return True
def cancel_job(jid):
    j=get_job(jid)
    if j["status"] in {"completed","failed","cancelled"}:return j
    _set_job(jid,status="cancelled")
    with _LOCK,_connect() as c:c.execute("UPDATE job_steps SET status='cancelled' WHERE job_id=? AND status IN ('queued','running')",(jid,))
    t=_RUNNING.get(jid)
    if t and not t.done():t.cancel()
    _event(jid,"cancel","Job cancelled by user.");return get_job(jid)
async def _run_one(jid,step,runner):
    if not _reserve(jid):_set_step(jid,step["id"],status="failed",error="Agent-call budget exhausted",finished_at=_now());return
    _set_step(jid,step["id"],status="running",started_at=_now(),attempts=int(step.get("attempts") or 0)+1);_event(jid,"step_started",f"{step['specialist']} started: {step['title']}",{"step_id":step["id"]})
    job=get_job(jid);by={s["id"]:s for s in job["steps"]};deps=[f"Output from {d}:\n{by[d]['output']}" for d in step.get("depends_on",[]) if d in by and by[d].get("output")];instruction=step["instruction"]+("\n\nUse these completed dependency outputs:\n"+"\n\n".join(deps) if deps else "")
    try:
        if step["specialist"]=="deep_research":
            from agentie.core.deep_research import run_deep_research
            result=await run_deep_research(instruction,runner,job["session_id"]);output=result["report"]
            _event(jid,"research_sources",f"Deep research collected {len(result['sources'])} sources.",{"queries":result["queries"],"sources":result["sources"]})
            _event(jid,"citation_verification","Citation verification completed.",result.get("verification") or {})
        else:output=await runner(instruction,step["specialist"],job["session_id"])
        _set_step(jid,step["id"],status="completed",output=output,error=None,finished_at=_now());_event(jid,"step_completed",f"Completed: {step['title']}",{"step_id":step["id"]})
    except asyncio.CancelledError:_set_step(jid,step["id"],status="cancelled",finished_at=_now());raise
    except Exception as exc:_set_step(jid,step["id"],status="failed",error=str(exc),finished_at=_now());_event(jid,"step_failed",f"Failed: {step['title']}: {exc}")
async def execute_job(jid,runner):
    try:
        _set_job(jid,status="running",error=None);_event(jid,"job_started","Job execution started.")
        while True:
            job=get_job(jid)
            if job["status"]=="cancelled":return
            steps=job["steps"];pending=[s for s in steps if s["status"]=="queued"]
            if not pending:break
            completed={s["id"] for s in steps if s["status"]=="completed"};failed={s["id"] for s in steps if s["status"] in {"failed","cancelled"}};run=[s for s in pending if set(s.get("depends_on",[]))<=completed];blocked=[s for s in pending if set(s.get("depends_on",[]))&failed]
            for s in blocked:_set_step(jid,s["id"],status="failed",error="Dependency failed",finished_at=_now())
            if not run:
                if blocked:continue
                _set_job(jid,status="failed",error="No runnable steps");return
            await asyncio.gather(*[_run_one(jid,s,runner) for s in run])
        job=get_job(jid);bad=[s for s in job["steps"] if s["status"]=="failed"];outs=[s["output"] for s in job["steps"] if s.get("output")]
        if bad:_set_job(jid,status="failed",final_output="\n\n".join(outs),error=f"{len(bad)} step(s) failed")
        else:_set_job(jid,status="completed",final_output=(outs[-1] if len(outs)==1 else "\n\n---\n\n".join(outs)),error=None);_event(jid,"job_completed","Job completed successfully.")
    except asyncio.CancelledError:_set_job(jid,status="cancelled")
    except Exception as exc:_set_job(jid,status="failed",error=str(exc));_event(jid,"job_failed",str(exc))
    finally:_RUNNING.pop(jid,None)
def start_job(jid,runner):
    e=_RUNNING.get(jid)
    if e and not e.done():return
    _RUNNING[jid]=asyncio.create_task(execute_job(jid,runner))
def resume_unfinished(runner):
    init_db()
    with _LOCK,_connect() as c:rows=c.execute("SELECT id FROM jobs WHERE status IN ('queued','running') ORDER BY created_at").fetchall();c.execute("UPDATE job_steps SET status='queued',started_at=NULL WHERE status='running'")
    for r in rows:start_job(str(r["id"]),runner)
    return len(rows)
def job_card(job):
    return {"type":"job_progress","id":job["id"],"goal":job["goal"],"status":job["status"],"completed_steps":job.get("completed_steps",0),"total_steps":job.get("total_steps",0),"provider_calls":job.get("provider_calls",0),"budget_provider_calls":job.get("budget_provider_calls",0),"final_output":job.get("final_output"),"error":job.get("error"),"steps":[{"id":s["id"],"title":s["title"],"specialist":s["specialist"],"status":s["status"],"attempts":s["attempts"],"error":s.get("error")} for s in job.get("steps",[])]}
