import re
import threading
import time
from typing import Any

_PENDING: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()
_TTL_SECONDS = 15 * 60

_DURATION_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:seconds?|secs?|minutes?|mins?|hours?|hrs?)\b", re.I)
_CLOCK_RE = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b")


def _clean(text: str) -> str:
    value = text.lower().strip()
    value = value.replace("tim,er", "timer").replace("tim er", "timer").replace("ti mer", "timer")
    value = value.replace("wheather", "weather").replace("weathr", "weather")
    value = re.sub(r"\s+", " ", value)
    return value


def _set(session_id: str, intent: str, original: str, **slots: Any) -> None:
    with _LOCK:
        _PENDING[session_id] = {
            "intent": intent,
            "original": original,
            "slots": slots,
            "created_at": time.time(),
        }


def clear_pending(session_id: str) -> None:
    with _LOCK:
        _PENDING.pop(session_id, None)


def _get(session_id: str) -> dict[str, Any] | None:
    with _LOCK:
        item = _PENDING.get(session_id)
        if not item:
            return None
        if time.time() - float(item.get("created_at", 0)) > _TTL_SECONDS:
            _PENDING.pop(session_id, None)
            return None
        return dict(item)


def detect_incomplete_intent(session_id: str, message: str) -> dict[str, Any] | None:
    """Recognize obvious local intents with missing slots and ask only for what's missing."""
    text = _clean(message)

    if "timer" in text and not _DURATION_RE.search(text):
        _set(session_id, "timer", message)
        return {"message": "How long should I set the timer for?", "routed_by": "clarification"}

    if "alarm" in text and not _CLOCK_RE.search(text):
        _set(session_id, "alarm", message)
        return {"message": "What time should I set the alarm for?", "routed_by": "clarification"}

    if re.search(r"\b(?:weather|forecast|temperature)\b", text):
        # Bare weather intent with no useful location after the keyword.
        match = re.search(r"\b(?:weather|forecast|temperature)\b(?:\s+(?:in|for|at))?\s*(.*)$", text)
        location = (match.group(1) if match else "").strip(" ?.!")
        if not location or location in {"please", "now", "today", "please now"}:
            _set(session_id, "weather", message)
            return {"message": "Which location should I check the weather for?", "routed_by": "clarification"}

    if re.search(r"\b(?:calculate|calculator|calc|work out|solve)\b", text):
        if not re.search(r"\d", text):
            _set(session_id, "calculation", message)
            return {"message": "What would you like me to calculate?", "routed_by": "clarification"}

    if re.search(r"\bconvert\b", text):
        # Need a value and two units.
        if not re.search(r"\d", text) or not re.search(r"\b(?:to|into|in)\b", text):
            _set(session_id, "conversion", message)
            return {"message": "What value and units should I convert?", "routed_by": "clarification"}

    if re.search(r"\bremind(?:er)?\b", text):
        has_when = bool(re.search(r"\b(?:in\s+\d|every\s+\d|every weekday|at\s+\d{1,2}:\d{2})", text))
        if not has_when:
            # Preserve any reminder text so the follow-up can just be a time.
            reminder_text = re.sub(r"^.*?\bremind(?:er)?(?: me)?(?: to)?\b", "", text).strip(" ?.!")
            _set(session_id, "reminder", message, reminder_text=reminder_text)
            return {"message": "When should I remind you?", "routed_by": "clarification"}

    return None


def consume_followup(session_id: str, message: str) -> dict[str, Any] | None:
    """Turn a short follow-up into a canonical command for the pending local intent."""
    pending = _get(session_id)
    if not pending:
        return None

    text = _clean(message)
    intent = pending["intent"]
    slots = pending.get("slots", {})

    # Users can abandon the pending loop naturally.
    if text in {"cancel", "never mind", "nevermind", "forget it", "stop"}:
        clear_pending(session_id)
        return {"cancelled": True, "message": "Okay, cancelled."}

    if intent == "timer":
        duration = _DURATION_RE.search(text)
        if duration:
            clear_pending(session_id)
            return {"command": f"set timer for {duration.group(0)}"}
        return {"message": "Tell me a duration, for example 20 seconds or 5 minutes."}

    if intent == "alarm":
        clock = _CLOCK_RE.search(text)
        if clock:
            clear_pending(session_id)
            return {"command": f"set alarm {clock.group(0)}"}
        return {"message": "Tell me a time such as 07:30 or 18:45."}

    if intent == "weather":
        location = message.strip(" ?.!")
        if location:
            clear_pending(session_id)
            return {"command": f"weather in {location}"}
        return {"message": "Which city or location?"}

    if intent == "calculation":
        expression = message.strip(" ?.!")
        if re.search(r"\d", expression):
            clear_pending(session_id)
            return {"command": f"calculate {expression}"}
        return {"message": "Give me the numbers or expression to calculate."}

    if intent == "conversion":
        value = message.strip(" ?.!")
        if re.search(r"\d", value) and re.search(r"\b(?:to|into|in)\b", value, re.I):
            clear_pending(session_id)
            return {"command": f"convert {value}"}
        return {"message": "For example: 10 kilometers to miles."}

    if intent == "reminder":
        reminder_text = str(slots.get("reminder_text") or "").strip()
        duration = _DURATION_RE.search(text)
        if duration and reminder_text:
            clear_pending(session_id)
            return {"command": f"remind me to {reminder_text} in {duration.group(0)}"}
        if duration and not reminder_text:
            # Need the reminder content next.
            _set(session_id, "reminder_text", pending.get("original", ""), when=duration.group(0))
            return {"message": "What should I remind you about?"}
        return {"message": "Tell me when, for example in 10 minutes."}

    if intent == "reminder_text":
        when = str(slots.get("when") or "").strip()
        reminder_text = message.strip(" ?.!")
        if reminder_text and when:
            clear_pending(session_id)
            return {"command": f"remind me to {reminder_text} in {when}"}

    return None
