from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agentie.core.external_triggers import publish_external_event
from agentie.core.mcp_client import execute_tool, get_server, inspect_server
from agentie.core.plugin_credentials import public_setup_state

WORKSPACE = Path.cwd() / "workspace"
STATE_FILE = WORKSPACE / "google_workspace_events.json"
_TASK: asyncio.Task | None = None
_POLL_SECONDS = 60


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _default() -> dict[str, Any]:
    return {
        "gmail_enabled": False,
        "calendar_enabled": False,
        "drive_watches": [],
        "gmail_seen_ids": [],
        "calendar_seen_ids": [],
        "last_poll_at": None,
        "last_error": None,
        "updated_at": _now(),
    }


def _load() -> dict[str, Any]:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    except Exception:
        data = {}
    base = _default()
    if isinstance(data, dict):
        base.update(data)
    base["drive_watches"] = [dict(x) for x in base.get("drive_watches") or [] if isinstance(x, dict)]
    base["gmail_seen_ids"] = [str(x) for x in base.get("gmail_seen_ids") or []][-300:]
    base["calendar_seen_ids"] = [str(x) for x in base.get("calendar_seen_ids") or []][-300:]
    return base


def _save(data: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now()
    STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def settings() -> dict[str, Any]:
    data = _load()
    return {
        "gmail_enabled": bool(data.get("gmail_enabled")),
        "calendar_enabled": bool(data.get("calendar_enabled")),
        "drive_watches": [dict(x) for x in data.get("drive_watches") or []],
        "last_poll_at": data.get("last_poll_at"),
        "last_error": data.get("last_error"),
    }


def update_settings(*, gmail_enabled: bool | None = None, calendar_enabled: bool | None = None) -> dict[str, Any]:
    data = _load()
    if gmail_enabled is not None:
        data["gmail_enabled"] = bool(gmail_enabled)
        if not gmail_enabled:
            data["gmail_seen_ids"] = []
    if calendar_enabled is not None:
        data["calendar_enabled"] = bool(calendar_enabled)
        if not calendar_enabled:
            data["calendar_seen_ids"] = []
    _save(data)
    return settings()


def add_drive_watch(item_id: str, *, kind: str = "file", label: str = "") -> dict[str, Any]:
    item_id = str(item_id or "").strip()[:500]
    kind = str(kind or "file").strip().casefold()
    if not item_id:
        raise ValueError("Google Drive file or folder ID is required.")
    if kind not in {"file", "folder"}:
        raise ValueError("Drive watch kind must be file or folder.")
    data = _load()
    existing = next((x for x in data["drive_watches"] if str(x.get("item_id")) == item_id and str(x.get("kind")) == kind), None)
    if existing:
        return dict(existing)
    row = {
        "id": "gw_" + hashlib.sha256(f"{kind}:{item_id}".encode()).hexdigest()[:12],
        "item_id": item_id,
        "kind": kind,
        "label": " ".join(str(label or "").strip().split())[:160],
        "baseline": None,
        "created_at": _now(),
        "last_checked_at": None,
        "last_error": None,
    }
    data["drive_watches"].append(row)
    _save(data)
    return dict(row)


def remove_drive_watch(watch_id: str) -> bool:
    data = _load()
    before = len(data["drive_watches"])
    data["drive_watches"] = [x for x in data["drive_watches"] if str(x.get("id")) != str(watch_id)]
    changed = len(data["drive_watches"]) != before
    if changed:
        _save(data)
    return changed


def _tool_name(info: dict[str, Any], *candidates: str) -> str | None:
    tools = info.get("tools") or []
    normalized = {re.sub(r"[^a-z0-9]", "", str(x.get("name") or "").casefold()): str(x.get("name") or "") for x in tools}
    for candidate in candidates:
        hit = normalized.get(re.sub(r"[^a-z0-9]", "", candidate.casefold()))
        if hit:
            return hit
    return None


def _content(result: dict[str, Any]) -> str:
    card = result.get("card") if isinstance(result, dict) else None
    if isinstance(card, dict):
        return str(card.get("content") or "")
    return str(result or "")


def _parse_jsonish(text: str) -> Any:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    first_obj = raw.find("{")
    first_arr = raw.find("[")
    starts = [x for x in (first_obj, first_arr) if x >= 0]
    if starts:
        start = min(starts)
        for end_char in ("}", "]"):
            end = raw.rfind(end_char)
            if end > start:
                try:
                    return json.loads(raw[start:end + 1])
                except Exception:
                    continue
    return None


def _walk_records(value: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if any(k in value for k in ("id", "messageId", "eventId", "fileId")):
            out.append(value)
        for child in value.values():
            out.extend(_walk_records(child))
    elif isinstance(value, list):
        for child in value:
            out.extend(_walk_records(child))
    return out


def _record_id(row: dict[str, Any]) -> str | None:
    for key in ("id", "messageId", "eventId", "fileId"):
        value = row.get(key)
        if value:
            return str(value)
    return None


def _records_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    text = _content(result)
    parsed = _parse_jsonish(text)
    if parsed is not None:
        rows = _walk_records(parsed)
        if rows:
            return rows
    ids = []
    for pattern in (r'"(?:id|messageId|eventId|fileId)"\s*:\s*"([^"\n]+)"', r"\b(?:id|messageId|eventId|fileId)\s*:\s*([^\s,}\]]+)"):
        for match in re.finditer(pattern, text, re.I):
            value = match.group(1).strip('"\'')
            if value and value not in ids:
                ids.append(value)
    return [{"id": x} for x in ids]


def _fingerprint(result: dict[str, Any]) -> str:
    text = _content(result)
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _event_payload(row: dict[str, Any], *, source_type: str) -> dict[str, Any]:
    keep = ("id", "messageId", "eventId", "fileId", "threadId", "subject", "from", "sender", "snippet", "name", "mimeType", "modifiedTime", "createdTime", "start", "end", "summary")
    payload = {k: row.get(k) for k in keep if row.get(k) is not None}
    payload["google_source"] = source_type
    return payload


async def _inspect() -> tuple[dict[str, Any] | None, str | None]:
    if not get_server("google-workspace"):
        return None, "Google Workspace MCP is not registered."
    try:
        return await inspect_server("google-workspace"), None
    except Exception as exc:
        return None, str(exc)[:700]


async def bridge_status(*, verify_connection: bool = False) -> dict[str, Any]:
    setup = public_setup_state("google-workspace")
    registered = bool(get_server("google-workspace"))
    connected = None
    tools: list[str] = []
    error = None
    if verify_connection and registered:
        info, error = await _inspect()
        connected = bool(info)
        if info:
            tools = [str(x.get("name") or "") for x in info.get("tools") or []]
    state = settings()
    return {
        **state,
        "registered": registered,
        "configured": bool(setup.get("configured")),
        "connected": connected,
        "connection_error": error,
        "tools": tools,
        "sources": [
            {"id": "gmail", "label": "Gmail inbox", "event_type": "email.received", "enabled": state["gmail_enabled"]},
            {"id": "calendar", "label": "Google Calendar", "event_type": "calendar.event.started", "enabled": state["calendar_enabled"]},
            {"id": "drive", "label": "Google Drive watches", "event_type": "drive.file.changed / drive.folder.changed", "enabled": bool(state["drive_watches"])},
        ],
        "poll_interval_seconds": _POLL_SECONDS,
        "note": "Gmail and Calendar use safe read-only polling through the connected Google Workspace MCP. Drive watches are explicit file/folder watches because the current MCP does not expose a global Drive push/change feed.",
    }


async def _poll_gmail(data: dict[str, Any], info: dict[str, Any]) -> int:
    tool = _tool_name(info, "searchEmails", "search_emails")
    if not tool:
        raise RuntimeError("Connected Google Workspace MCP does not expose Gmail searchEmails.")
    result = await execute_tool("google-workspace", tool, {"query": "newer_than:2d", "maxResults": 30})
    rows = _records_from_result(result)
    ids = [x for x in (_record_id(row) for row in rows) if x]
    previous = set(map(str, data.get("gmail_seen_ids") or []))
    emitted = 0
    if previous:
        for row in rows:
            rid = _record_id(row)
            if not rid or rid in previous:
                continue
            publish_external_event("email.received", _event_payload(row, source_type="gmail"), source="google_workspace", external_id=f"gmail:{rid}")
            emitted += 1
    data["gmail_seen_ids"] = list(dict.fromkeys(ids + list(previous)))[:300]
    return emitted


async def _poll_calendar(data: dict[str, Any], info: dict[str, Any]) -> int:
    tool = _tool_name(info, "listEvents", "list_events")
    if not tool:
        raise RuntimeError("Connected Google Workspace MCP does not expose Calendar listEvents.")
    now = datetime.now(timezone.utc)
    args = {
        "calendarId": "primary",
        "timeMin": (now - timedelta(minutes=3)).isoformat().replace("+00:00", "Z"),
        "timeMax": (now + timedelta(minutes=3)).isoformat().replace("+00:00", "Z"),
        "maxResults": 50,
        "singleEvents": True,
        "orderBy": "startTime",
    }
    result = await execute_tool("google-workspace", tool, args)
    rows = _records_from_result(result)
    ids = [x for x in (_record_id(row) for row in rows) if x]
    previous = set(map(str, data.get("calendar_seen_ids") or []))
    emitted = 0
    if previous:
        for row in rows:
            rid = _record_id(row)
            if not rid or rid in previous:
                continue
            publish_external_event("calendar.event.started", _event_payload(row, source_type="calendar"), source="google_workspace", external_id=f"calendar:{rid}")
            emitted += 1
    data["calendar_seen_ids"] = list(dict.fromkeys(ids + list(previous)))[:300]
    return emitted


async def _poll_drive_watch(watch: dict[str, Any], info: dict[str, Any]) -> int:
    kind = str(watch.get("kind") or "file")
    if kind == "folder":
        tool = _tool_name(info, "listFolder", "list_folder")
        if not tool:
            raise RuntimeError("Connected Google Workspace MCP does not expose Drive listFolder.")
        result = await execute_tool("google-workspace", tool, {"folderId": watch["item_id"], "pageSize": 100})
        event_type = "drive.folder.changed"
    else:
        tool = _tool_name(info, "getFileMetadata", "get_file_metadata")
        if not tool:
            raise RuntimeError("Connected Google Workspace MCP does not expose Drive getFileMetadata.")
        result = await execute_tool("google-workspace", tool, {"fileId": watch["item_id"]})
        event_type = "drive.file.changed"
    fingerprint = _fingerprint(result)
    old = watch.get("baseline")
    watch["baseline"] = fingerprint
    watch["last_checked_at"] = _now()
    watch["last_error"] = None
    if old and old != fingerprint:
        publish_external_event(event_type, {"watch_id": watch["id"], "item_id": watch["item_id"], "kind": kind, "label": watch.get("label") or ""}, source="google_workspace", external_id=f"{watch['id']}:{fingerprint}")
        return 1
    return 0


async def poll_enabled_sources() -> dict[str, Any]:
    data = _load()
    if not data.get("gmail_enabled") and not data.get("calendar_enabled") and not data.get("drive_watches"):
        return {"polled": False, "reason": "No Google Workspace event sources are enabled.", "events": 0}
    info, error = await _inspect()
    if not info:
        data["last_poll_at"] = _now()
        data["last_error"] = error or "Google Workspace is not connected."
        _save(data)
        return {"polled": False, "reason": data["last_error"], "events": 0}
    emitted = 0
    errors: list[str] = []
    if data.get("gmail_enabled"):
        try:
            emitted += await _poll_gmail(data, info)
        except Exception as exc:
            errors.append(f"Gmail: {str(exc)[:400]}")
    if data.get("calendar_enabled"):
        try:
            emitted += await _poll_calendar(data, info)
        except Exception as exc:
            errors.append(f"Calendar: {str(exc)[:400]}")
    for watch in data.get("drive_watches") or []:
        try:
            emitted += await _poll_drive_watch(watch, info)
        except Exception as exc:
            watch["last_checked_at"] = _now()
            watch["last_error"] = str(exc)[:400]
            errors.append(f"Drive {watch.get('label') or watch.get('item_id')}: {str(exc)[:300]}")
    data["last_poll_at"] = _now()
    data["last_error"] = " | ".join(errors)[:1000] or None
    _save(data)
    return {"polled": True, "events": emitted, "errors": errors, "last_poll_at": data["last_poll_at"]}


async def _loop() -> None:
    while True:
        try:
            await poll_enabled_sources()
        except Exception:
            pass
        await asyncio.sleep(_POLL_SECONDS)


def start_google_workspace_event_bridge() -> None:
    global _TASK
    if _TASK and not _TASK.done():
        return
    _TASK = asyncio.create_task(_loop())
