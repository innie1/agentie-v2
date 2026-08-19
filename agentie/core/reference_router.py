import json
import re
from datetime import datetime, timedelta
from typing import Any

from agentie.core.memory_store import get_context, set_context
from agentie.tools import local_utility_tools as local_utils
from agentie.tools import productivity_tools as productivity

_DURATION_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(seconds?|secs?|sec|s|minutes?|mins?|min|m|hours?|hrs?|hr|h)\b", re.I)


def _seconds(match: re.Match[str]) -> float:
    value = float(match.group(1)); unit = match.group(2).lower()
    if unit.startswith("h"): return value * 3600
    if unit.startswith("m"): return value * 60
    return value


def _load_reminders() -> list[dict]:
    try: return json.loads(productivity.REMINDERS.read_text(encoding="utf-8")) if productivity.REMINDERS.exists() else []
    except Exception: return []


def remember_active_from_card(session_id: str, card: dict[str, Any] | None) -> None:
    if not isinstance(card, dict): return
    if card.get("type") == "multi":
        for item in reversed(card.get("items") or []):
            child = item.get("card") if isinstance(item, dict) else None
            if isinstance(child, dict):
                remember_active_from_card(session_id, child)
                if get_context(session_id, "active_object"): return
        return
    card_type = str(card.get("type") or "")
    if card_type in {"timer", "alarm", "reminder", "schedule", "uploaded_file", "note", "task", "tasks"}:
        set_context(session_id, "active_object", {"type": card_type, "card": card})


def try_active_reference(session_id: str, message: str) -> dict[str, Any] | None:
    active = get_context(session_id, "active_object")
    if not isinstance(active, dict): return None
    card = active.get("card") if isinstance(active.get("card"), dict) else {}
    object_type = str(active.get("type") or card.get("type") or "")
    text = re.sub(r"\s+", " ", message.lower().strip())
    duration = _DURATION_RE.search(text)
    change_words = bool(re.search(r"\b(?:make|change|set|restart|reset|instead|again)\b", text))
    add_words = bool(re.search(r"\b(?:add|plus|increase|extend)\b", text))
    reference_words = bool(re.search(r"\b(?:it|that|this|timer|alarm|reminder)\b", text))

    if object_type in {"timer", "alarm"}:
        timer_id = str(card.get("id") or "")
        if not timer_id: return None
        if duration and reference_words and (change_words or add_words):
            requested = _seconds(duration)
            if add_words:
                # Add to remaining time, not the original duration.
                due_raw = card.get("due_at")
                try:
                    due = datetime.fromisoformat(str(due_raw)); now = datetime.now(due.tzinfo) if due.tzinfo else datetime.now(); current = max(0.0, (due-now).total_seconds())
                except Exception: current = float(card.get("duration_seconds") or 0)
                requested += current
            refreshed = local_utils._restart_timer(timer_id, requested)
            if not refreshed: return None
            new_card = dict(card)
            new_card.update({"type":object_type,"id":timer_id,"status":refreshed.get("status","running"),"duration_seconds":requested,"due_at":refreshed.get("due_at")})
            set_context(session_id, "active_object", {"type":object_type,"card":new_card})
            pretty = int(requested) if float(requested).is_integer() else round(requested, 1)
            return {"message": f"{'Timer' if object_type=='timer' else 'Alarm'} updated to {pretty} seconds from now.", "card": new_card, "routed_by":"active_reference"}
        if reference_words and re.search(r"\b(?:cancel|stop|dismiss)\b", text):
            with local_utils._TIMER_LOCK:
                item = local_utils._TIMERS.get(timer_id)
                if not item: return None
                item["status"] = "cancelled"
            new_card = dict(card); new_card["status"] = "cancelled"
            set_context(session_id, "active_object", {"type":object_type,"card":new_card})
            return {"message": f"{'Timer' if object_type=='timer' else 'Alarm'} cancelled.", "card": new_card, "routed_by":"active_reference"}

    if object_type == "reminder":
        reminder_id = str(card.get("id") or "")
        if not reminder_id: return None
        if duration and reference_words and (change_words or add_words):
            seconds = _seconds(duration); items = _load_reminders(); target = next((x for x in items if str(x.get("id")) == reminder_id), None)
            if target is None: return None
            try:
                old_due = datetime.fromisoformat(str(target.get("due_at"))); now = datetime.now(old_due.tzinfo) if old_due.tzinfo else datetime.now()
            except Exception: now = datetime.now(); old_due = now
            new_due = old_due + timedelta(seconds=seconds) if add_words else now + timedelta(seconds=seconds)
            target["due_at"] = new_due.isoformat(timespec="seconds"); target["status"] = "scheduled"; productivity._save(productivity.REMINDERS, items)
            new_card = {"type":"reminder", **target}; set_context(session_id,"active_object",{"type":"reminder","card":new_card})
            return {"message":f"Updated that reminder for {new_due.strftime('%H:%M:%S')}.","card":new_card,"routed_by":"active_reference"}
        if reference_words and re.search(r"\b(?:cancel|delete|remove|dismiss)\b", text):
            items = _load_reminders(); target = next((x for x in items if str(x.get("id")) == reminder_id), None)
            if target is None: return None
            target["status"] = "cancelled"; productivity._save(productivity.REMINDERS, items)
            new_card = {"type":"reminder", **target}; set_context(session_id,"active_object",{"type":"reminder","card":new_card})
            return {"message":"Reminder cancelled.","card":new_card,"routed_by":"active_reference"}
    return None
