import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from agents import function_tool

STORE = Path.cwd() / "workspace" / "approvals.json"

def _load():
    if not STORE.exists(): return []
    try: return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception: return []

def _save(items):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")

@function_tool
def request_approval(action: str, reason: str) -> str:
    """Create a pending approval request before an externally consequential action."""
    items = _load()
    item = {"id": str(uuid.uuid4())[:8], "action": action[:500], "reason": reason[:1000], "status": "pending", "created_at": datetime.now(timezone.utc).isoformat()}
    items.append(item); _save(items)
    return json.dumps(item)

@function_tool
def list_approvals() -> str:
    """List pending and previous approval requests."""
    return json.dumps(_load(), indent=2)
