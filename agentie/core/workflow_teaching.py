from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

WORKSPACE = Path.cwd() / "workspace"
WORKFLOWS_FILE = WORKSPACE / "taught_workflows.json"
ACTIVE_FILE = WORKSPACE / "taught_workflow_active.json"
_LOCK = threading.Lock()
_SENSITIVE_FIELD = re.compile(r"\b(password|passcode|pin|secret|api[ -]?key|access[ -]?token|auth(?:entication)?[ -]?token|private[ -]?key|cvv|cvc|security[ -]?code|card[ -]?number)\b",re.I)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _load(path: Path, default):
    try:
        value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
        return value
    except Exception:
        return default


def _save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def _clean_name(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" .?!\"“”")
    if not text:
        raise ValueError("Give the workflow a short name before teaching it.")
    return text[:120]


def active_recording() -> dict[str, Any] | None:
    with _LOCK:
        item = _load(ACTIVE_FILE, None)
        return dict(item) if isinstance(item, dict) else None


def start_recording(name: str, owner_agent_id: str | None = None) -> dict[str, Any]:
    name = _clean_name(name)
    with _LOCK:
        existing = _load(ACTIVE_FILE, None)
        if isinstance(existing, dict):
            raise ValueError(f"Already teaching “{existing.get('name') or 'a workflow'}”. Stop or cancel that recording first.")
        item = {
            "id": "wf_" + uuid.uuid4().hex[:10],
            "name": name,
            "owner_agent_id": owner_agent_id,
            "status": "recording",
            "steps": [],
            "created_at": _now(),
            "updated_at": _now(),
        }
        _save(ACTIVE_FILE, item)
        return dict(item)


def _same_step(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return str(a.get("command") or "").strip() == str(b.get("command") or "").strip()


def record_step(kind: str, command: str, metadata: dict[str, Any] | None = None) -> dict[str, Any] | None:
    command = re.sub(r"\s+", " ", str(command or "")).strip()
    if not command:
        return active_recording()
    with _LOCK:
        item = _load(ACTIVE_FILE, None)
        if not isinstance(item, dict):
            return None
        step = {
            "id": "st_" + uuid.uuid4().hex[:8],
            "kind": str(kind or "action")[:40],
            "command": command[:5000],
            "metadata": metadata or {},
            "recorded_at": _now(),
        }
        steps = item.setdefault("steps", [])
        if not steps or not _same_step(steps[-1], step):
            steps.append(step)
        item["updated_at"] = _now()
        _save(ACTIVE_FILE, item)
        return dict(item)


def record_browser_event(event: dict[str, Any]) -> dict[str, Any] | None:
    kind = str(event.get("kind") or "").strip().lower()
    if kind == "click":
        target = re.sub(r"\s+", " ", str(event.get("target") or "screen item")).strip()[:180]
        return record_step("click", f"click {target}", {"target": target})
    if kind == "fill":
        field = re.sub(r"\s+", " ", str(event.get("field") or "field")).strip()[:180]
        sensitive=bool(event.get("secret")) or bool(_SENSITIVE_FIELD.search(field))
        if sensitive:
            return record_step("fill", f"fill {field} with <secret>", {"field": field, "secret": True, "requires_input": True})
        value = str(event.get("value") or "")[:5000]
        return record_step("fill", f"fill {field} with {value}", {"field": field, "value": value})
    if kind == "key":
        key = str(event.get("key") or "").strip()
        if key:
            return record_step("key", f"press {key}", {"key": key})
    if kind == "open":
        url = str(event.get("url") or "").strip()
        if url.startswith(("http://", "https://")):
            return record_step("open", f"open {url}", {"url": url})
    return active_recording()


def _workflows() -> list[dict[str, Any]]:
    value = _load(WORKFLOWS_FILE, [])
    return value if isinstance(value, list) else []


def list_workflows(owner_agent_id: str | None = None) -> list[dict[str, Any]]:
    with _LOCK:
        items = [dict(x) for x in _workflows()]
    if owner_agent_id:
        owned = [x for x in items if not x.get("owner_agent_id") or str(x.get("owner_agent_id")) == str(owner_agent_id)]
        return list(reversed(owned))
    return list(reversed(items))


def get_workflow(name_or_id: str, owner_agent_id: str | None = None) -> dict[str, Any] | None:
    wanted = _clean_name(name_or_id).casefold()
    for item in list_workflows(owner_agent_id):
        if str(item.get("id") or "").casefold() == wanted or str(item.get("name") or "").casefold() == wanted:
            return item
    return None


def stop_recording() -> dict[str, Any]:
    with _LOCK:
        item = _load(ACTIVE_FILE, None)
        if not isinstance(item, dict):
            raise ValueError("Teach mode is not currently recording a workflow.")
        if not item.get("steps"):
            ACTIVE_FILE.unlink(missing_ok=True)
            raise ValueError("No browser actions were recorded, so no workflow was saved.")
        item["status"] = "saved"
        item["updated_at"] = _now()
        items = _workflows()
        items = [x for x in items if str(x.get("name") or "").casefold() != str(item.get("name") or "").casefold()]
        items.append(item)
        _save(WORKFLOWS_FILE, items)
        ACTIVE_FILE.unlink(missing_ok=True)
        return dict(item)


def cancel_recording() -> dict[str, Any] | None:
    with _LOCK:
        item = _load(ACTIVE_FILE, None)
        ACTIVE_FILE.unlink(missing_ok=True)
        return dict(item) if isinstance(item, dict) else None


def delete_workflow(name_or_id: str, owner_agent_id: str | None = None) -> dict[str, Any]:
    target = get_workflow(name_or_id, owner_agent_id)
    if not target:
        raise ValueError("Taught workflow was not found.")
    with _LOCK:
        items = [x for x in _workflows() if str(x.get("id")) != str(target.get("id"))]
        _save(WORKFLOWS_FILE, items)
    return target


def mark_run(workflow_id: str) -> None:
    with _LOCK:
        items = _workflows()
        for item in items:
            if str(item.get("id")) == str(workflow_id):
                item["run_count"] = int(item.get("run_count") or 0) + 1
                item["last_run_at"] = _now()
                item["updated_at"] = _now()
                break
        _save(WORKFLOWS_FILE, items)


def workflow_card(item: dict[str, Any], card_type: str = "taught_workflow") -> dict[str, Any]:
    return {
        "type": card_type,
        "id": item.get("id"),
        "name": item.get("name"),
        "status": item.get("status"),
        "owner_agent_id": item.get("owner_agent_id"),
        "step_count": len(item.get("steps") or []),
        "steps": [
            {
                "id": step.get("id"),
                "kind": step.get("kind"),
                "command": step.get("command"),
                "requires_input": bool((step.get("metadata") or {}).get("requires_input")),
            }
            for step in item.get("steps") or []
        ],
        "run_count": int(item.get("run_count") or 0),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
    }
