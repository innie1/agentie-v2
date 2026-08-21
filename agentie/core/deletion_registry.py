from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

WORKSPACE = Path.cwd() / "workspace"
DELETIONS_FILE = WORKSPACE / "deletions.json"
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _load() -> list[dict[str, Any]]:
    try:
        value = json.loads(DELETIONS_FILE.read_text(encoding="utf-8")) if DELETIONS_FILE.exists() else []
        return value if isinstance(value, list) else []
    except Exception:
        return []


def _save(items: list[dict[str, Any]]) -> None:
    DELETIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    DELETIONS_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


def remember_deleted(entity_type: str, entity_id: str, name: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    kind = str(entity_type or "").strip().casefold()
    eid = str(entity_id or "").strip()
    label = str(name or "").strip()
    if not kind or not eid:
        raise ValueError("Deletion tombstones require an entity type and id.")
    with _LOCK:
        items = _load()
        existing = next((x for x in items if str(x.get("entity_type", "")).casefold() == kind and str(x.get("entity_id", "")) == eid), None)
        if existing:
            return dict(existing)
        item = {
            "entity_type": kind,
            "entity_id": eid,
            "name": label or None,
            "deleted_at": _now(),
            "metadata": dict(metadata or {}),
        }
        items.append(item)
        _save(items)
        return dict(item)


def find_deleted(entity_type: str, key: str) -> dict[str, Any] | None:
    kind = str(entity_type or "").strip().casefold()
    wanted = str(key or "").strip().casefold()
    if not kind or not wanted:
        return None
    with _LOCK:
        for item in reversed(_load()):
            if str(item.get("entity_type", "")).casefold() != kind:
                continue
            if str(item.get("entity_id", "")).casefold() == wanted or str(item.get("name", "")).casefold() == wanted:
                return dict(item)
    return None


def already_deleted(entity_type: str, key: str) -> bool:
    return find_deleted(entity_type, key) is not None
