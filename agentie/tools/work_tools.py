from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from agents import function_tool

WORKSPACE = Path.cwd() / "workspace"
CONTACTS_FILE = WORKSPACE / "contacts.json"
MONITORS_FILE = WORKSPACE / "website_monitors.json"


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default


def _save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def _clean(value: str, limit: int = 300) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


@function_tool
def plan_task(goal: str) -> str:
    """Create a short execution plan and identify which Agentie capabilities are likely needed."""
    text = _clean(goal, 2000)
    low = text.lower()
    steps: list[dict[str, str]] = []

    def add(action: str, tool: str, permission: str = "read"):
        if not any(item["action"] == action for item in steps):
            steps.append({"action": action, "tool": tool, "permission": permission})

    if re.search(r"\b(search|research|find|compare|latest|website|web)\b", low):
        add("Gather current information", "web research")
    if re.search(r"\b(file|document|pdf|docx|csv|xlsx|spreadsheet|report)\b", low):
        add("Read or analyze source files", "files/documents")
    if re.search(r"\b(csv|xlsx|spreadsheet|budget|data|numbers|chart|finance)\b", low):
        add("Analyze structured data", "spreadsheet/data")
    if re.search(r"\b(email|mail|reply|inbox)\b", low):
        add("Prepare the email action", "email plugin", "write")
    if re.search(r"\b(calendar|meeting|appointment|schedule)\b", low):
        add("Check or prepare calendar action", "calendar plugin", "write")
    if re.search(r"\b(github|repo|repository|issue|pull request|\bpr\b|commit|ci)\b", low):
        add("Inspect or update GitHub", "GitHub", "write" if re.search(r"\b(create|update|fix|commit|merge|close|delete)\b", low) else "read")
    if re.search(r"\b(contact|phone|recipient|person|people)\b", low):
        add("Resolve people or recipients", "contacts")
    if re.search(r"\b(monitor|watch|track|alert|notify when|changes)\b", low):
        add("Create a monitoring checkpoint", "website monitor", "write")
    if not steps:
        add("Understand the goal and choose the smallest capable tool", "agent planner")
    if len(steps) > 1:
        add("Combine results and verify completion", "agent planner")

    return json.dumps({"goal": text, "steps": steps, "approval_required": any(s["permission"] != "read" for s in steps)}, ensure_ascii=False)


@function_tool
def save_contact(name: str, email: str = "", phone: str = "", company: str = "", notes: str = "") -> str:
    """Save or update a local contact. This only writes Agentie's local contacts file."""
    name = _clean(name, 160)
    if not name:
        return "Contact name is required."
    email = _clean(email, 240)
    if email and not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
        return "That email address does not look valid."
    items = _load(CONTACTS_FILE, [])
    key = name.casefold()
    existing = next((x for x in items if str(x.get("name", "")).casefold() == key), None)
    payload = {
        "name": name,
        "email": email,
        "phone": _clean(phone, 80),
        "company": _clean(company, 160),
        "notes": _clean(notes, 500),
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    if existing:
        existing.update(payload)
        action = "Updated"
    else:
        payload["id"] = uuid.uuid4().hex[:10]
        items.append(payload)
        action = "Saved"
    _save(CONTACTS_FILE, items)
    return f"{action} contact {name}."


@function_tool
def find_contacts(query: str) -> str:
    """Search locally saved contacts by name, email, phone, company, or notes."""
    q = _clean(query, 200).casefold()
    items = _load(CONTACTS_FILE, [])
    if not q:
        matches = items[:50]
    else:
        matches = [x for x in items if q in " ".join(str(x.get(k, "")) for k in ("name", "email", "phone", "company", "notes")).casefold()][:50]
    safe = [{k: item.get(k, "") for k in ("id", "name", "email", "phone", "company", "notes")} for item in matches]
    return json.dumps(safe, ensure_ascii=False)


@function_tool
def create_website_monitor(url: str, label: str = "", check_for: str = "changes") -> str:
    """Create a local website-monitor definition for later scheduled checks."""
    url = _clean(url, 1000)
    if not re.match(r"^https?://", url, re.I):
        return "Website monitors require an http:// or https:// URL."
    items = _load(MONITORS_FILE, [])
    item = {
        "id": uuid.uuid4().hex[:10],
        "url": url,
        "label": _clean(label, 160) or url,
        "check_for": _clean(check_for, 500) or "changes",
        "status": "active",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "last_checked_at": None,
    }
    items.append(item)
    _save(MONITORS_FILE, items)
    return json.dumps(item, ensure_ascii=False)


@function_tool
def list_website_monitors() -> str:
    """List Agentie's locally configured website monitors."""
    return json.dumps(_load(MONITORS_FILE, []), ensure_ascii=False)
