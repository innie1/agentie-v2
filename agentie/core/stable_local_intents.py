from __future__ import annotations

import re
from typing import Any

from agentie.tools import local_utility_tools as utilities

_TIMER_UNIT = r"seconds?|secs?|sec|s|minutes?|mins?|min|m|hours?|hrs?|hr|h"


def _seconds(value: float, unit: str) -> float:
    unit = unit.lower()
    if unit.startswith("h"):
        return value * 3600
    if unit.startswith("m"):
        return value * 60
    return value


def _pretty(seconds: float) -> str:
    if seconds % 3600 == 0:
        n = int(seconds // 3600)
        return f"{n} hour" + ("s" if n != 1 else "")
    if seconds % 60 == 0:
        n = int(seconds // 60)
        return f"{n} minute" + ("s" if n != 1 else "")
    n = int(seconds) if float(seconds).is_integer() else seconds
    return f"{n} second" + ("s" if n != 1 else "")


def parse_timer_create(message: str) -> dict[str, Any] | None:
    """Parse high-confidence timer creation requests without using the model.

    This intentionally accepts terse conversational forms such as:
      timer 10s
      timer for 10 s
      a timer for 10 seconds
      set/start/make a timer for 10 seconds to check the build
    It does not handle updates/cancellation; those remain active-reference operations.
    """
    text = " ".join(str(message or "").strip().split())
    if not text:
        return None

    patterns = [
        re.compile(
            rf"^(?:please\s+)?(?:(?:set|start|make|give me)\s+)?(?:a\s+)?timer(?:\s+for)?\s+(\d+(?:\.\d+)?)\s*({_TIMER_UNIT})(?:\s+(?:to|for|because|so i can|so that i can)\s+(.+))?$",
            re.I,
        ),
        re.compile(
            rf"^(?:please\s+)?(?:(?:set|start|make|give me)\s+)?(?:a\s+)?(\d+(?:\.\d+)?)\s*({_TIMER_UNIT})\s+timer(?:\s+(?:to|for|because|so i can|so that i can)\s+(.+))?$",
            re.I,
        ),
    ]
    match = patterns[0].match(text) or patterns[1].match(text)
    if not match:
        return None

    value = float(match.group(1))
    seconds = _seconds(value, match.group(2))
    if seconds <= 0 or seconds > 7 * 24 * 3600:
        return {"message": "Timer must be between 1 second and 7 days.", "card": None}

    reason = (match.group(3) or "").strip(" .?!")
    item = utilities._create_timer(seconds, reason or "Timer", "timer")
    card: dict[str, Any] = {
        "type": "timer",
        "id": item["id"],
        "status": item["status"],
        "duration_seconds": seconds,
        "due_at": item["due_at"],
    }
    if reason:
        card["reason"] = reason
    return {
        "message": f"Timer set for {_pretty(seconds)}" + (f" — {reason}." if reason else "."),
        "card": card,
    }


def route_stable_local_intent(message: str) -> dict[str, Any] | None:
    timer = parse_timer_create(message)
    if timer is not None:
        return timer
    return None
