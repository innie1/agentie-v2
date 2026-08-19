import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agents import function_tool

STORE = Path.cwd() / "workspace" / "tasks.json"
ACTIVE_STATUSES = {"pending", "working"}


def _load():
    if not STORE.exists():
        return []
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(tasks):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(tasks, indent=2, ensure_ascii=False), encoding="utf-8")


def _normalize_title(title: str) -> str:
    return " ".join(str(title or "").strip().lower().split())


@function_tool
def create_task(title: str, steps: list[str]) -> str:
    """Create a tracked task with ordered steps.

    If an active task with the same normalized title already exists, return the
    existing task instead of creating a duplicate.
    """
    tasks = _load()
    clean_title = str(title or "").strip()[:200]
    normalized = _normalize_title(clean_title)
    if not normalized:
        raise ValueError("Task title is required.")

    for existing in tasks:
        if (
            _normalize_title(existing.get("title", "")) == normalized
            and existing.get("status") in ACTIVE_STATUSES
        ):
            return json.dumps({
                "reused_existing": True,
                "task": existing,
            })

    task = {
        "id": str(uuid.uuid4())[:8],
        "title": clean_title,
        "status": "pending",
        "steps": [
            {"text": str(step)[:500], "done": False}
            for step in steps[:20]
            if str(step).strip()
        ],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    tasks.append(task)
    _save(tasks)
    return json.dumps({"reused_existing": False, "task": task})


@function_tool
def list_tasks() -> str:
    """List tracked tasks and their status."""
    return json.dumps(_load(), indent=2)


@function_tool
def update_task(task_id: str, status: str) -> str:
    """Update task status to pending, working, completed, or failed."""
    allowed = {"pending", "working", "completed", "failed"}
    if status not in allowed:
        raise ValueError("Invalid status")
    tasks = _load()
    for task in tasks:
        if task.get("id") == task_id:
            task["status"] = status
            _save(tasks)
            return f"Task {task_id} is now {status}."
    return "Task not found."
