import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from agents import function_tool

STORE = Path.cwd() / "workspace" / "tasks.json"

def _load():
    if not STORE.exists(): return []
    try: return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception: return []

def _save(tasks):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(tasks, indent=2, ensure_ascii=False), encoding="utf-8")

@function_tool
def create_task(title: str, steps: list[str]) -> str:
    """Create a tracked task with ordered steps."""
    tasks = _load()
    task = {"id": str(uuid.uuid4())[:8], "title": title[:200], "status": "pending", "steps": [{"text": s[:500], "done": False} for s in steps[:20]], "created_at": datetime.now(timezone.utc).isoformat()}
    tasks.append(task); _save(tasks)
    return json.dumps(task)

@function_tool
def list_tasks() -> str:
    """List tracked tasks and their status."""
    return json.dumps(_load(), indent=2)

@function_tool
def update_task(task_id: str, status: str) -> str:
    """Update task status to pending, working, completed, or failed."""
    allowed = {"pending", "working", "completed", "failed"}
    if status not in allowed: raise ValueError("Invalid status")
    tasks = _load()
    for task in tasks:
        if task.get("id") == task_id:
            task["status"] = status; _save(tasks); return f"Task {task_id} is now {status}."
    return "Task not found."
