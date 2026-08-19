import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agents import function_tool

STORE = Path.cwd() / "workspace" / "approvals.json"


def _load():
    if not STORE.exists():
        return []
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(items):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


def get_approval(approval_id: str):
    for item in _load():
        if item.get("id") == approval_id:
            return item
    return None


def approval_is_granted(action: str, approval_id: str | None = None) -> bool:
    return any(
        item.get("action") == action
        and item.get("status") == "approved"
        and not item.get("consumed_at")
        and (approval_id is None or item.get("id") == approval_id)
        for item in _load()
    )


def consume_approval(action: str) -> bool:
    """Consume one previously approved action exactly once."""
    items = _load()
    for item in items:
        if item.get("action") == action and item.get("status") == "approved" and not item.get("consumed_at"):
            item["consumed_at"] = datetime.now(timezone.utc).isoformat()
            item["status"] = "consumed"
            _save(items)
            return True
    return False


def create_approval(action: str, reason: str, metadata: dict | None = None):
    items = _load()
    for item in items:
        if item.get("action") == action and item.get("status") == "pending":
            return item
    item = {
        "id": str(uuid.uuid4())[:8],
        "action": action[:500],
        "reason": reason[:1000],
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if metadata:
        item["metadata"] = metadata
    items.append(item)
    _save(items)
    return item


def resolve_approval(approval_id: str, approved: bool):
    items = _load()
    for item in items:
        if item.get("id") == approval_id:
            if item.get("status") != "pending":
                raise ValueError("Approval has already been resolved.")
            item["status"] = "approved" if approved else "denied"
            item["resolved_at"] = datetime.now(timezone.utc).isoformat()
            _save(items)
            return item
    raise ValueError("Approval not found.")


@function_tool
def request_approval(action: str, reason: str) -> str:
    """Create a pending approval request before an externally consequential action."""
    return json.dumps(create_approval(action, reason))


@function_tool
def list_approvals() -> str:
    """List pending and previous approval requests."""
    return json.dumps(_load(), indent=2)
