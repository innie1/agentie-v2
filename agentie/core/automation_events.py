from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

WORKSPACE=Path.cwd()/"workspace"
EVENTS=WORKSPACE/"automation_events.json"
_LOCK=threading.Lock()


def _now()->str:return datetime.now().astimezone().isoformat(timespec="seconds")
def _load()->list[dict[str,Any]]:
    try:
        value=json.loads(EVENTS.read_text(encoding="utf-8")) if EVENTS.exists() else []
        return value if isinstance(value,list) else []
    except Exception:return []
def _save(items:list[dict[str,Any]])->None:
    EVENTS.parent.mkdir(parents=True,exist_ok=True);EVENTS.write_text(json.dumps(items[-1000:],indent=2,ensure_ascii=False),encoding="utf-8")


def publish_event(event_type:str,payload:dict[str,Any]|None=None,*,source:str="agentie",dedupe_key:str|None=None)->dict[str,Any]:
    """Publish a real internal event for event-driven routines.

    This is intentionally local and durable. It is not a second scheduler: the
    existing routine worker consumes these events and runs matching routines.
    """
    event_type=str(event_type or "").strip().casefold()
    if not event_type:raise ValueError("Event type is required.")
    with _LOCK:
        items=_load()
        if dedupe_key:
            existing=next((x for x in reversed(items) if str(x.get("dedupe_key") or "")==str(dedupe_key)),None)
            if existing:return dict(existing)
        item={"id":"evt_"+uuid.uuid4().hex[:10],"type":event_type,"payload":dict(payload or {}),"source":str(source or "agentie")[:120],"dedupe_key":str(dedupe_key or "")[:300] or None,"created_at":_now(),"delivered_routine_ids":[],"closed_at":None}
        items.append(item);_save(items);return dict(item)


def pending_events(limit:int=100)->list[dict[str,Any]]:
    with _LOCK:return [dict(x) for x in _load() if not x.get("closed_at")][:max(1,min(int(limit),500))]


def mark_delivered(event_id:str,routine_id:str)->dict[str,Any]|None:
    with _LOCK:
        items=_load();target=next((x for x in items if str(x.get("id"))==str(event_id)),None)
        if not target:return None
        delivered={str(x) for x in target.get("delivered_routine_ids") or []};delivered.add(str(routine_id));target["delivered_routine_ids"]=sorted(delivered);_save(items);return dict(target)


def close_event(event_id:str)->dict[str,Any]|None:
    with _LOCK:
        items=_load();target=next((x for x in items if str(x.get("id"))==str(event_id)),None)
        if not target:return None
        target["closed_at"]=target.get("closed_at") or _now();_save(items);return dict(target)


def recent_events(limit:int=100)->list[dict[str,Any]]:
    with _LOCK:return [dict(x) for x in reversed(_load()[-max(1,min(int(limit),500)):])]
