import json
from pathlib import Path
from agents import function_tool

STORE = Path.cwd() / "workspace" / "memory.json"

def _load():
    if not STORE.exists(): return {}
    try: return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception: return {}

def _save(data):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

@function_tool
def remember(key: str, value: str) -> str:
    """Save a non-sensitive user preference, goal, or useful fact for later."""
    data = _load(); data[key[:80]] = value[:2000]; _save(data)
    return f"Remembered: {key[:80]}"

@function_tool
def recall_memory(key: str) -> str:
    """Recall one saved memory by key."""
    return str(_load().get(key, "No memory found for that key."))

@function_tool
def list_memories() -> str:
    """List saved memory keys."""
    keys = sorted(_load().keys())
    return "\n".join(keys) if keys else "No saved memories."
