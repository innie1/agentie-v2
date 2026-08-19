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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with _LOCK, _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              goal TEXT NOT NULL,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              final_output TEXT,
              error TEXT,
              provider_calls INTEGER NOT NULL DEFAULT 0,
              budget_provider_calls INTEGER NOT NULL DEFAULT 8
            );
            CREATE TABLE IF NOT EXISTS job_steps (
              id TEXT PRIMARY KEY,
              job_id TEXT NOT NULL,
              position INTEGER NOT NULL,
              title TEXT NOT NULL,
              instruction TEXT NOT NULL,
              specialist TEXT NOT NULL,
              status TEXT NOT NULL,
              depends_on_json TEXT NOT NULL,
              output TEXT,
              error TEXT,
              attempts INTEGER NOT NULL DEFAULT 0,
              started_at TEXT,
              finished_at TEXT,
              FOREIGN KEY(job_id) REFERENCES jobs(id)
            );
            CREATE INDEX IF NOT EXISTS idx_job_steps_job ON job_steps(job_id, position);
            CREATE TABLE IF NOT EXISTS job_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              job_id TEXT NOT NULL,
              kind TEXT NOT NULL,
              message TEXT NOT NULL,
              metadata_json TEXT,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_job_events_job ON job_events(job_id, id);
            """
        )


def _event(job_id: str, kind: str, message: str, metadata: dict[str, Any] | None = None) -> None:
    with _LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO job_events(job_id,kind,message,metadata_json,created_at) VALUES(?,?,?,?,?)",
            (job_id, kind, message, json.dumps(metadata or {}, ensure_ascii=False), _now()),
        )


def _specialist(text: str) -> str:
    lower = text.lower()
    if re.search(r"\b(github|repository|repo|pull request|issue|commit|branch)\b", lower): return "github"
    if re.search(r"\b(code|coding|python|javascript|typescript|bug|debug|implement|refactor|test|file|pdf|csv|json|yaml|zip)\b", lower): return "coding"
    if re.search(r"\b(research|search|web|latest|sources?|compare|investigate|find out|news)\b", lower): return "research"
    return "general"


def make_plan(goal: str) -> list[dict[str, Any]]:
    """Create a deterministic, cheap initial plan. The execution loop may re-plan failures later."""
    cleaned = re.sub(r"\s+", " ", goal.strip())
    lower = cleaned.lower()
    steps: list[dict[str, Any]] = []

    researchish = bool(re.search(r"\b(research|search|latest|compare|investigate|sources?|web)\b", lower))
    synthesis = bool(re.search(r"\b(report|summary|summarize|write|draft|document|pdf|presentation)\b", lower))
    codingish = bool(re.search(r"\b(code|build|implement|fix|debug|refactor|test)\b", lower))

    if researchish and synthesis:
        research_id = "s1"
        steps.append({"id": research_id, "title": "Research", "instruction": f"Research this goal carefully and return source-grounded findings: {cleaned}", "specialist": "research", "depends_on": []})
        steps.append({"id": "s2", "title": "Synthesize", "instruction": f"Using the completed research, produce the requested final deliverable for: {cleaned}", "specialist": "general", "depends_on": [research_id]})
        return steps

    if codingish and re.search(r"\b(test|verify|check)\b", lower):
        steps.append({"id": "s1", "title": "Implement", "instruction": cleaned, "specialist": "coding", "depends_on": []})
        steps.append({"id": "s2", "title": "Verify", "instruction": "Verify the implementation, run appropriate checks, and report failures clearly.", "specialist": "coding", "depends_on": ["s1"]})
        return steps

    clauses = [x.strip(" .") for x in re.split(r"\s*(?:;|\bthen\b|\band then\b)\s*", cleaned, flags=re.I) if x.strip(" .")]
    if len(clauses) == 1:
        # Split explicit multi-goal comma/and requests only when each clause starts with an action verb.
        parts = re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+", cleaned, flags=re.I)
        action = re.compile(r"^(?:research|search|find|compare|analyze|analyse|write|create|build|fix|test|inspect|read|summarize|summarise|check|look|calculate|convert|show)\b", re.I)
        if len(parts) > 1 and sum(bool(action.search(p.strip())) for p in parts) >= 2:
            clauses = [p.strip(" .") for p in parts if p.strip(" .")]

    previous: str | None = None
    for idx, clause in enumerate(clauses[:8], start=1):
        sid = f"s{idx}"
        # "then" semantics are sequential; otherwise clauses can run in parallel.
        depends = [previous] if previous and re.search(r"\bthen\b", cleaned, re.I) else []
        steps.append({"id": sid, "title": clause[:64], "instruction": clause, "specialist": _specialist(clause), "depends_on": depends})
        previous = sid
    return steps or [{"id":"s1","title":"Complete goal","instruction":cleaned,"specialist":_specialist(cleaned),"depends_on":[]}]


def create_job(session_id: str, goal: str, budget_provider_calls: int = 8) -> dict[str, Any]:
    init_db()
    job_id = uuid.uuid4().hex[:10]
    now = _now()
    plan = make_plan(goal)
    with _LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO jobs(id,session_id,goal,status,created_at,updated_at,budget_provider_calls) VALUES(?,?,?,?,?,?,?)",
            (job_id, session_id, goal, "queued", now, now, max(0, min(int(budget_provider_calls), 50))),
        )
        for pos, step in enumerate(plan):
            conn.execute(
                "INSERT INTO job_steps(id,job_id,position,title,instruction,specialist,status,depends_on_json) VALUES(?,?,?,?,?,?,?,?)",
                (step["id"], job_id, pos, step["title"], step["instruction"], step["specialist"], "queued", json.dumps(step.get("depends_on", []))),
            )
    _event(job_id, "plan", f"Created plan with {len(plan)} step(s).", {"steps": plan})
    return get_job(job_id)


def get_job(job_id: str) -> dict[str, Any]:
    init_db()
    with _LOCK, _connect() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not job: raise KeyError(job_id)
        rows = conn.execute("SELECT * FROM job_steps WHERE job_id=? ORDER BY position", (job_id,)).fetchall()
    steps = []
    for row in rows:
        item = dict(row); item["depends_on"] = json.loads(item.pop("depends_on_json") or "[]"); steps.append(item)
    data = dict(job); data["steps"] = steps
    data["completed_steps"] = sum(1 for s in steps if s["status"] == "completed")
    data["total_steps"] = len(steps)
    return data


def list_jobs(session_id: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
    init_db()
    with _LOCK, _connect() as conn:
        if session_id:
            rows = conn.execute("SELECT id FROM jobs WHERE session_id=? ORDER BY created_at DESC LIMIT ?", (session_id, limit)).fetchall()
        else:
            rows = conn.execute("SELECT id FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [get_job(str(r["id"])) for r in rows]


def job_events(job_id: str, limit: int = 100) -> list[dict[str, Any]]:
    init_db()
    with _LOCK, _connect() as conn:
        rows = conn.execute("SELECT * FROM job_events WHERE job_id=? ORDER BY id DESC LIMIT ?", (job_id, limit)).fetchall()
    items=[]
    for row in reversed(rows):
        item=dict(row); item["metadata"] = json.loads(item.pop("metadata_json") or "{}"); items.append(item)
    return items


def _set_job(job_id: str, **fields: Any) -> None:
    if not fields: return
    fields["updated_at"] = _now()
    sql = ",".join(f"{key}=?" for key in fields)
    with _LOCK, _connect() as conn:
        conn.execute(f"UPDATE jobs SET {sql} WHERE id=?", (*fields.values(), job_id))


def _set_step(job_id: str, step_id: str, **fields: Any) -> None:
    if not fields: return
    sql = ",".join(f"{key}=?" for key in fields)
    with _LOCK, _connect() as conn:
        conn.execute(f"UPDATE job_steps SET {sql} WHERE job_id=? AND id=?", (*fields.values(), job_id, step_id))
    _set_job(job_id)


def cancel_job(job_id: str) -> dict[str, Any]:
    job = get_job(job_id)
    if job["status"] in {"completed","failed","cancelled"}: return job
    _set_job(job_id, status="cancelled")
    with _LOCK, _connect() as conn:
        conn.execute("UPDATE job_steps SET status='cancelled' WHERE job_id=? AND status IN ('queued','running')", (job_id,))
    task = _RUNNING.get(job_id)
    if task and not task.done(): task.cancel()
    _event(job_id, "cancel", "Job cancelled by user.")
    return get_job(job_id)


async def _run_one(job_id: str, step: dict[str, Any], runner: StepRunner) -> None:
    _set_step(job_id, step["id"], status="running", started_at=_now(), attempts=int(step.get("attempts") or 0)+1)
    _event(job_id, "step_started", f"{step['specialist']} started: {step['title']}", {"step_id": step["id"], "specialist": step["specialist"]})
    job = get_job(job_id)
    dependency_outputs = []
    by_id = {s["id"]: s for s in job["steps"]}
    for dep in step.get("depends_on", []):
        if dep in by_id and by_id[dep].get("output"):
            dependency_outputs.append(f"Output from {dep}:\n{by_id[dep]['output']}")
    instruction = step["instruction"]
    if dependency_outputs:
        instruction += "\n\nUse these completed dependency outputs:\n" + "\n\n".join(dependency_outputs)
    try:
        output = await runner(instruction, step["specialist"], job["session_id"])
        _set_step(job_id, step["id"], status="completed", output=output, error=None, finished_at=_now())
        _event(job_id, "step_completed", f"Completed: {step['title']}", {"step_id": step["id"]})
    except asyncio.CancelledError:
        _set_step(job_id, step["id"], status="cancelled", finished_at=_now()); raise
    except Exception as exc:
        _set_step(job_id, step["id"], status="failed", error=str(exc), finished_at=_now())
        _event(job_id, "step_failed", f"Failed: {step['title']}: {exc}", {"step_id": step["id"]})


async def execute_job(job_id: str, runner: StepRunner) -> None:
    try:
        _set_job(job_id, status="running", error=None)
        _event(job_id, "job_started", "Job execution started.")
        while True:
            job = get_job(job_id)
            if job["status"] == "cancelled": return
            steps = job["steps"]
            pending = [s for s in steps if s["status"] == "queued"]
            if not pending: break
            completed = {s["id"] for s in steps if s["status"] == "completed"}
            failed = {s["id"] for s in steps if s["status"] in {"failed","cancelled"}}
            runnable = [s for s in pending if set(s.get("depends_on", [])) <= completed]
            blocked = [s for s in pending if set(s.get("depends_on", [])) & failed]
            for step in blocked:
                _set_step(job_id, step["id"], status="failed", error="Dependency failed", finished_at=_now())
            if not runnable:
                if blocked: continue
                _set_job(job_id, status="failed", error="No runnable steps; dependency cycle or missing dependency.")
                _event(job_id, "job_failed", "Job stopped because the plan had no runnable steps.")
                return
            # Independent runnable steps execute in parallel.
            await asyncio.gather(*[_run_one(job_id, step, runner) for step in runnable])

        job = get_job(job_id)
        failed_steps = [s for s in job["steps"] if s["status"] == "failed"]
        outputs = [s["output"] for s in job["steps"] if s.get("output")]
        if failed_steps:
            _set_job(job_id, status="failed", final_output="\n\n".join(outputs), error=f"{len(failed_steps)} step(s) failed")
            _event(job_id, "job_failed", f"Job finished with {len(failed_steps)} failed step(s).")
        else:
            final_output = outputs[-1] if len(outputs) == 1 else "\n\n---\n\n".join(outputs)
            _set_job(job_id, status="completed", final_output=final_output, error=None)
            _event(job_id, "job_completed", "Job completed successfully.")
    except asyncio.CancelledError:
        _set_job(job_id, status="cancelled")
    except Exception as exc:
        _set_job(job_id, status="failed", error=str(exc)); _event(job_id, "job_failed", str(exc))
    finally:
        _RUNNING.pop(job_id, None)


def start_job(job_id: str, runner: StepRunner) -> None:
    existing = _RUNNING.get(job_id)
    if existing and not existing.done(): return
    _RUNNING[job_id] = asyncio.create_task(execute_job(job_id, runner))


def resume_unfinished(runner: StepRunner) -> int:
    init_db()
    with _LOCK, _connect() as conn:
        rows = conn.execute("SELECT id FROM jobs WHERE status IN ('queued','running') ORDER BY created_at").fetchall()
        # A process restart means previously running steps need to become queued again.
        conn.execute("UPDATE job_steps SET status='queued', started_at=NULL WHERE status='running'")
    for row in rows: start_job(str(row["id"]), runner)
    return len(rows)


def job_card(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "job_progress",
        "id": job["id"],
        "goal": job["goal"],
        "status": job["status"],
        "completed_steps": job.get("completed_steps", 0),
        "total_steps": job.get("total_steps", 0),
        "provider_calls": job.get("provider_calls", 0),
        "budget_provider_calls": job.get("budget_provider_calls", 0),
        "steps": [
            {"id":s["id"],"title":s["title"],"specialist":s["specialist"],"status":s["status"],"attempts":s["attempts"],"error":s.get("error")}
            for s in job.get("steps", [])
        ],
    }


def should_delegate(agent_type: str, message: str) -> bool:
    if agent_type != "manager": return False
    lower = message.lower()
    if len(message) >= 180: return True
    signals = sum(bool(re.search(p, lower)) for p in [r"\bresearch\b",r"\bbuild\b",r"\bcompare\b",r"\breport\b",r"\bthen\b",r"\bmultiple\b",r"\bparallel\b",r"\bdelegate\b"])
    return signals >= 2
