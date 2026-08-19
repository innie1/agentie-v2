import re
from typing import Any

from agentie.core.memory_store import get_context, set_context
from agentie.tools import local_utility_tools as local_utils

_DURATION_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(seconds?|secs?|sec|s|minutes?|mins?|min|m|hours?|hrs?|hr|h)\b", re.I)


def _seconds(match: re.Match[str]) -> float:
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit.startswith("h"): return value * 3600
    if unit.startswith("m"): return value * 60
    return value


def remember_active_from_card(session_id: str, card: dict[str, Any] | None) -> None:
    if not isinstance(card, dict):
        return
    if card.get("type") == "multi":
        for item in reversed(card.get("items") or []):
            child = item.get("card") if isinstance(item, dict) else None
            if isinstance(child, dict):
                remember_active_from_card(session_id, child)
                if get_context(session_id, "active_object"):
                    return
        return
    card_type = str(card.get("type") or "")
    if card_type in {"timer", "alarm", "reminder", "schedule", "uploaded_file", "note", "task", "tasks"}:
        set_context(session_id, "active_object", {"type": card_type, "card": card})


def try_active_reference(session_id: str, message: str) -> dict[str, Any] | None:
    """Resolve short follow-ups such as 'make it 30 seconds instead' locally."""
    active = get_context(session_id, "active_object")
    if not isinstance(active, dict):
        return None
    card = active.get("card") if isinstance(active.get("card"), dict) else {}
    object_type = str(active.get("type") or card.get("type") or "")
    text = re.sub(r"\s+", " ", message.lower().strip())

    if object_type == "timer":
        timer_id = str(card.get("id") or "")
        if not timer_id:
            return None

        duration = _DURATION_RE.search(text)
        change_words = bool(re.search(r"\b(?:make|change|set|restart|reset|instead|again)\b", text))
        add_words = bool(re.search(r"\b(?:add|plus|increase|extend)\b", text))
        reference_words = bool(re.search(r"\b(?:it|that|timer|this)\b", text))

        if duration and reference_words and (change_words or add_words):
            requested = _seconds(duration)
            if add_words:
                current = float(card.get("duration_seconds") or card.get("seconds") or 0)
                requested += current
            refreshed = local_utils._restart_timer(timer_id, requested)
            if not refreshed:
                return None
            new_card = {
                "type": "timer",
                "id": timer_id,
                "status": refreshed.get("status", "running"),
                "duration_seconds": requested,
                "due_at": refreshed.get("due_at"),
            }
            set_context(session_id, "active_object", {"type": "timer", "card": new_card})
            pretty = int(requested) if requested.is_integer() else requested
            return {"message": f"Timer set for {pretty} seconds.", "card": new_card, "routed_by": "active_reference"}

        if reference_words and re.search(r"\b(?:cancel|stop)\b", text):
            result = local_utils.cancel_timer(timer_id)
            new_card = dict(card); new_card["status"] = "cancelled"
            set_context(session_id, "active_object", {"type": "timer", "card": new_card})
            return {"message": str(result), "card": new_card, "routed_by": "active_reference"}

    return None
