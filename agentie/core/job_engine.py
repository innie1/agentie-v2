import asyncio
import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from agentie.core.npc_brain import job_title
WORKSPACE=Path.cwd()/"workspace";DB_PATH=WORKSPACE/"agentie_jobs.sqlite3";_LOCK=threading.Lock();_RUNNING:dict[str,asyncio.Task]={};StepRunner=Callable[[str,str,str],Awaitable[str]]
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
def _artifact_kind(text):
    x=str(text or "").lower()
    if re.search(r"\bpdf\b",x):return "pdf"
    if re.search(r"\b(?:docx|docs? file|word document|word file)\b",x):return "docx"
    if re.search(r"\b(?:xlsx|excel|spreadsheet)\b",x):return "xlsx"
    if re.search(r"\b(?:pptx|powerpoint|presentation|slide deck|slides)\b",x):return "pptx"
    return None
def make_plan(goal):
    clean=re.sub(r"\s+"," ",goal.strip());low=clean.lower();research=bool(re.search(r"\b(research|search|latest|compare|investigate|sources?|web|deep research|deep search|deeper search)\b",low));synthesis=bool(re.search(r"\b(report|summary|summarize|write|draft|document|pdf|presentation|research)\b",low));coding=bool(re.search(r"\b(code|build|implement|fix|debug|refactor|test)\b",low));artifact=_artifact_kind(clean)
    if research and artifact and re.search(r"\b(?:create|make|generate|export|save|turn|convert)\b",low):
        marker=re.search(r"\b(?:and\s+then|then|and|afterwards?|after\s+that)\s+(?=(?:create|make|generate|export|save|turn|convert)\b)",clean,re.I)
        research_instruction=(clean[:marker.start()] if marker else re.sub(r"\b(?:create|make|generate|export|save|turn|convert)\b[\s\S]*$","",clean,flags=re.I)).strip(" ,.;") or clean
        artifact_instruction=(clean[marker.end():] if marker else f"Create a {artifact.upper()} file from the completed research result").strip(" ,.;")
        if not re.match(r"^(?:create|make|generate|export|save|turn|convert)\b",artifact_instruction,re.I):artifact_instruction=f"Create {artifact_instruction}"
        return [{"id":"s1","title":"Research","instruction":research_instruction,"specialist":"deep_research","depends_on":[]},{"id":"s2","title":f"Create {artifact.upper()} file","instruction":artifact_instruction,"specialist":f"artifact_{artifact}","depends_on":["s1"]}]
    if research and (synthesis or "deep search" in low or "deeper search" in low):return [{"id":"s1","title":"Deep research","instruction":clean,"specialist":"deep_research","depends_on":[]}]
    if coding and re.search(r"\b(test|verify|check)\b",low):return [{"id":"s1","title":"Implement","instruction":clean,"specialist":"coding","depends_on":[]},{"id":"s2","title":"Verify","instruction":"Verify the implementation, run appropriate checks, and report failures clearly.","specialist":"coding","depends_on":["s1"]}]
    sequential=bool(re.search(r"\bthen\b",clean,re.I));clauses=[x.strip(" .") for x in re.split(r"\s*(?:;|\bthen\b|\band then\b)\s*",clean,flags=re.I) if x.strip(" .")]
    if len(clauses)==1:
        parts=re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+",clean,flags=re.I);action=re.compile(r"^(?:research|search|find|compare|analyze|analyse|write|create|build|fix|test|inspect|read|summarize|summarise|check|look|calculate|convert|show)\b",re.I)
        if len(parts)>1 and sum(bool(action.search(p.strip())) for p in parts)>=2:clauses=[p.strip(" .") for p in parts if p.strip(" .")]
    out=[];prev=None
    for i,clause in enumerate(clauses[:8],1):sid=f"s{i}";out.append({"id":sid,"title":clause[:64],"instruction":clause,"specialist":_specialist(clause),"depends_on":[prev] if sequential and prev else []});prev=sid
    return out or [{"id":"s1","title":"Complete goal","instruction":clean,"specialist":_specialist(clean),"depends_on":[]}]
def create_job(session_id,goal,budget_provider_calls=8,preferred_role=None):
    init_db();jid=uuid.uuid4().hex[:10];now=_now();plan=make_plan(goal);budget=max(0,min(int(budget_provider_calls),50));preferred=str(preferred_role or "").strip().lower()
    if preferred:
        for step in plan:
            if step["specialist"]!="deep_research" and not str(step["specialist"]).startswith("artifact_"):step["specialist"]=preferred
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
def jobs_for_agent(agent_id,limit=30):return list_jobs(f"agent:{agent_id}:",limit)+[j for j in list_jobs(None,limit*3) if str(j.get("session_id","")).startswith(f"agent:{agent_id}:") and j not in list_jobs(f"agent:{agent_id}:",limit)]
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
def pause_job(jid):
    j=get_job(jid)
    if j["status"] in {"completed","failed","cancelled","paused"}:return j
    _set_job(jid,status="paused");t=_RUNNING.get(jid)
    if t and not t.done():t.cancel()
    with _LOCK,_connect() as c:c.execute("UPDATE job_steps SET status='queued',started_at=NULL WHERE job_id=? AND status='running'",(jid,))
    _event(jid,"pause","Job paused by user.");return get_job(jid)
def resume_job(jid,runner):
    j=get_job(jid)
    if j["status"] not in {"paused","failed","queued"}:return j
    with _LOCK,_connect() as c:c.execute("UPDATE job_steps SET status='queued',error=NULL,started_at=NULL,finished_at=NULL WHERE job_id=? AND status='failed'",(jid,))
    _set_job(jid,status="queued",error=None);_event(jid,"resume","Job resumed.");start_job(jid,runner);return get_job(jid)
def cancel_job(jid):
    j=get_job(jid)
    if j["status"] in {"completed","failed","cancelled"}:return j
    _set_job(jid,status="cancelled")
    with _LOCK,_connect() as c:c.execute("UPDATE job_steps SET status='cancelled' WHERE job_id=? AND status IN ('queued','running')",(jid,))
    t=_RUNNING.get(jid)
    if t and not t.done():t.cancel()
    _event(jid,"cancel","Job cancelled by user.");return get_job(jid)
def _create_artifact_step(job,step,by):
    deps=[str(by[d].get("output") or "").strip() for d in step.get("depends_on",[]) if d in by and str(by[d].get("output") or "").strip()]
    content="\n\n".join(deps).strip()
    if not content:raise ValueError("Artifact step has no completed source result.")
    kind=str(step.get("specialist") or "").removeprefix("artifact_")
    from agentie.core.artifact_naming import creator_from_session
    from agentie.core.result_memory import existing_artifact,remember_artifact
    existing=existing_artifact(job["session_id"],kind,content)
    if existing:card=existing;reused=True
    else:
        creator=creator_from_session(job["session_id"])
        if kind=="pdf":
            from agentie.core.pdf_service import create_pdf
            card=create_pdf(content,None,creator,step.get("instruction"));
        else:
            from agentie.core.office_artifacts import create_docx,create_pptx,create_xlsx
            card=create_docx(content,None,creator,step.get("instruction")) if kind=="docx" else create_xlsx(content,None,creator,step.get("instruction")) if kind=="xlsx" else create_pptx(content,None,creator,step.get("instruction"))
        remember_artifact(job["session_id"],kind,content,card);reused=False
    _event(job["id"],"artifact_created",("Reused existing " if reused else "Created ")+str(card.get("document_name") or card.get("name") or kind.upper()),{"step_id":step["id"],"kind":kind,"card":card,"reused":reused})
    return ("Already created" if reused else "Created")+f" “{card.get('document_name') or card.get('name')}” as {card.get('name')}."
async def _run_one(jid,step,runner):
    local_artifact=str(step.get("specialist") or "").startswith("artifact_")
    if not local_artifact and not _reserve(jid):_set_step(jid,step["id"],status="failed",error="Agent-call budget exhausted",finished_at=_now());return
    _set_step(jid,step["id"],status="running",started_at=_now(),attempts=int(step.get("attempts") or 0)+1);_event(jid,"step_started",f"{step['specialist']} started: {step['title']}",{"step_id":step["id"]})
    job=get_job(jid);by={s["id"]:s for s in job["steps"]};deps=[f"Output from {d}:\n{by[d]['output']}" for d in step.get("depends_on",[]) if d in by and by[d].get("output")];instruction=step["instruction"]+("\n\nUse these completed dependency outputs:\n"+"\n\n".join(deps) if deps and not local_artifact else "")
    try:
        if local_artifact:output=_create_artifact_step(job,step,by)
        elif step["specialist"]=="deep_research":
            from agentie.core.deep_research import run_deep_research
            result=await run_deep_research(instruction,runner,job["session_id"])
            sources=result.get("sources") or []
            if not sources:raise RuntimeError("Research failed: no usable web sources were retrieved. The file step was not run.")
            output=str(result.get("report") or "").strip()
            if not output:raise RuntimeError("Research failed: no usable report was produced. The file step was not run.")
            _event(jid,"research_sources",f"Deep research collected {len(sources)} sources.",{"queries":result.get("queries") or [],"sources":sources});_event(jid,"citation_verification","Citation verification completed.",result.get("verification") or {})
        else:output=await runner(instruction,step["specialist"],job["session_id"])
        _set_step(jid,step["id"],status="completed",output=output,error=None,finished_at=_now());_event(jid,"step_completed",f"Completed: {step['title']}",{"step_id":step["id"]})
    except asyncio.CancelledError:
        if get_job(jid)["status"]=="paused":_set_step(jid,step["id"],status="queued",started_at=None)
        else:_set_step(jid,step["id"],status="cancelled",finished_at=_now())
        raise
    except Exception as exc:_set_step(jid,step["id"],status="failed",error=str(exc),finished_at=_now());_event(jid,"step_failed",f"Failed: {step['title']}: {exc}")
async def execute_job(jid,runner):
    try:
        _set_job(jid,status="running",error=None);_event(jid,"job_started","Job execution started.")
        while True:
            job=get_job(jid)
            if job["status"] in {"cancelled","paused"}:return
            steps=job["steps"];pending=[s for s in steps if s["status"]=="queued"]
            if not pending:break
            completed={s["id"] for s in steps if s["status"]=="completed"};failed={s["id"] for s in steps if s["status"] in {"failed","cancelled"}};run=[s for s in pending if set(s.get("depends_on",[]))<=completed];blocked=[s for s in pending if set(s.get("depends_on",[]))&failed]
            for s in blocked:_set_step(jid,s["id"],status="failed",error="Dependency failed",finished_at=_now())
            if not run:
                if blocked:continue
                _set_job(jid,status="failed",error="No runnable steps");_event(jid,"job_failed","No runnable steps.");return
            await asyncio.gather(*[_run_one(jid,s,runner) for s in run])
        job=get_job(jid);bad=[s for s in job["steps"] if s["status"]=="failed"];outs=[s["output"] for s in job["steps"] if s.get("output")]
        if bad:_set_job(jid,status="failed",final_output="\n\n".join(outs),error=f"{len(bad)} step(s) failed");_event(jid,"job_failed",f"Job finished with {len(bad)} failed step(s).")
        else:_set_job(jid,status="completed",final_output=(outs[-1] if len(outs)==1 else "\n\n---\n\n".join(outs)),error=None);_event(jid,"job_completed","Job completed successfully.")
    except asyncio.CancelledError:
        if get_job(jid)["status"]!="paused":_set_job(jid,status="cancelled")
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
    title=job_title(job.get("goal"));artifacts=[]
    try:artifacts=[e.get("metadata",{}).get("card") for e in job_events(job["id"],100) if e.get("kind")=="artifact_created" and isinstance(e.get("metadata",{}).get("card"),dict)]
    except Exception:pass
    return {"type":"job_progress","id":job["id"],"title":title,"goal":title,"request":job.get("goal"),"status":job["status"],"completed_steps":job.get("completed_steps",0),"total_steps":job.get("total_steps",0),"provider_calls":job.get("provider_calls",0),"budget_provider_calls":job.get("budget_provider_calls",0),"final_output":job.get("final_output"),"error":job.get("error"),"artifacts":artifacts,"steps":[{"id":s["id"],"title":s["title"],"specialist":s["specialist"],"status":s["status"],"attempts":s["attempts"],"error":s.get("error")} for s in job.get("steps",[])]}
def poll_job_completion_events(limit=20):
    """Return newly completed/failed jobs once so the existing local-event UI can alert the user."""
    init_db();now=datetime.now(timezone.utc)
    with _LOCK,_connect() as c:rows=c.execute("SELECT id,status,updated_at FROM jobs WHERE status IN ('completed','failed') ORDER BY updated_at DESC LIMIT ?",(max(1,limit*4),)).fetchall()
    events=[]
    for row in rows:
        try:
            age=(now-datetime.fromisoformat(str(row["updated_at"]))).total_seconds()
            if age>86400:continue
        except Exception:pass
        jid=str(row["id"]);history=job_events(jid,120)
        if any(e.get("kind")=="completion_notified" for e in history):continue
        if not any(e.get("kind") in {"job_completed","job_failed"} for e in history):continue
        job=get_job(jid);card=job_card(job);status=str(job.get("status"));title=card.get("title") or "Agent job"
        events.append({"message":f"{title} {'completed successfully' if status=='completed' else 'failed'}.","card":card})
        _event(jid,"completion_notified","Completion notification delivered.",{"status":status})
        if len(events)>=limit:break
    return list(reversed(events))