import ast
import json
import math
import operator
import os
import platform
import shutil
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from agents import function_tool

WORKSPACE = Path.cwd() / "workspace"
REMINDERS = WORKSPACE / "reminders.json"
NOTES = WORKSPACE / "notes.json"


def _load(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")

_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_ALLOWED_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _eval_math(node):
    if isinstance(node, ast.Expression):
        return _eval_math(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        return _ALLOWED_BINOPS[type(node.op)](_eval_math(node.left), _eval_math(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
        return _ALLOWED_UNARY[type(node.op)](_eval_math(node.operand))
    raise ValueError("Unsupported calculator expression.")


@function_tool
def calculate(expression: str) -> str:
    """Evaluate a basic arithmetic expression locally without an external API."""
    tree = ast.parse(expression, mode="eval")
    value = _eval_math(tree)
    if isinstance(value, float) and (math.isinf(value) or math.isnan(value)):
        raise ValueError("Invalid numeric result.")
    return str(value)


_CONVERSIONS = {
    ("km", "mi"): lambda x: x * 0.621371,
    ("mi", "km"): lambda x: x / 0.621371,
    ("m", "ft"): lambda x: x * 3.28084,
    ("ft", "m"): lambda x: x / 3.28084,
    ("kg", "lb"): lambda x: x * 2.2046226218,
    ("lb", "kg"): lambda x: x / 2.2046226218,
    ("c", "f"): lambda x: x * 9 / 5 + 32,
    ("f", "c"): lambda x: (x - 32) * 5 / 9,
    ("l", "gal"): lambda x: x * 0.264172,
    ("gal", "l"): lambda x: x / 0.264172,
}


@function_tool
def convert_unit(value: float, from_unit: str, to_unit: str) -> str:
    """Convert common units locally."""
    key = (from_unit.strip().lower(), to_unit.strip().lower())
    if key not in _CONVERSIONS:
        raise ValueError("Unsupported conversion.")
    result = _CONVERSIONS[key](float(value))
    return f"{result:.6g} {to_unit}"


@function_tool
def create_reminder(text: str, due_in_minutes: float, repeat_minutes: float = 0) -> str:
    """Create a persistent local reminder. repeat_minutes=0 means one-time."""
    if due_in_minutes <= 0:
        raise ValueError("due_in_minutes must be positive.")
    items = _load(REMINDERS, [])
    now = datetime.now()
    item = {
        "id": str(uuid.uuid4())[:8],
        "text": text[:500],
        "status": "scheduled",
        "created_at": now.isoformat(timespec="seconds"),
        "due_at": (now + timedelta(minutes=due_in_minutes)).isoformat(timespec="seconds"),
        "repeat_minutes": max(0, float(repeat_minutes)),
    }
    items.append(item)
    _save(REMINDERS, items)
    return json.dumps(item)


@function_tool
def list_reminders() -> str:
    """List persistent reminders."""
    return json.dumps(_load(REMINDERS, []), indent=2)


@function_tool
def cancel_reminder(reminder_id: str) -> str:
    """Cancel a persistent reminder by ID."""
    items = _load(REMINDERS, [])
    for item in items:
        if item.get("id") == reminder_id:
            item["status"] = "cancelled"
            _save(REMINDERS, items)
            return f"Cancelled reminder {reminder_id}."
    return "Reminder not found."


@function_tool
def save_note(title: str, content: str) -> str:
    """Save or replace a local note by title."""
    notes = _load(NOTES, {})
    notes[title[:120]] = {"content": content[:10000], "updated_at": datetime.now().isoformat(timespec="seconds")}
    _save(NOTES, notes)
    return f"Saved note: {title[:120]}"


@function_tool
def list_notes() -> str:
    """List note titles."""
    notes = _load(NOTES, {})
    return json.dumps(sorted(notes.keys()))


@function_tool
def read_note(title: str) -> str:
    """Read a local note by title."""
    notes = _load(NOTES, {})
    item = notes.get(title)
    return item.get("content", "Note not found.") if item else "Note not found."


@function_tool
def system_status() -> str:
    """Return local Agentie computer/runtime status without external APIs."""
    disk = shutil.disk_usage(Path.cwd())
    data = {
        "os": platform.platform(),
        "python": platform.python_version(),
        "hostname": platform.node(),
        "cwd": str(Path.cwd()),
        "disk_total_gb": round(disk.total / 1024**3, 1),
        "disk_free_gb": round(disk.free / 1024**3, 1),
        "process_id": os.getpid(),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    return json.dumps(data)
