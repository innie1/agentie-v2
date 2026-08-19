import ast
import json
import operator
import re
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from agentie.tools import local_utility_tools as utilities
from agentie.tools import productivity_tools as productivity


_DURATION_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>seconds?|secs?|minutes?|mins?|hours?|hrs?)",
    re.IGNORECASE,
)


def _duration_seconds(message: str) -> float | None:
    match = _DURATION_RE.search(message)
    if not match:
        return None
    value = float(match.group("value"))
    unit = match.group("unit").lower()
    if unit.startswith(("hour", "hr")):
        return value * 3600
    if unit.startswith(("minute", "min")):
        return value * 60
    return value


def _pretty_duration(seconds: float) -> str:
    if seconds % 3600 == 0:
        value = int(seconds // 3600)
        return f"{value} hour" + ("s" if value != 1 else "")
    if seconds % 60 == 0:
        value = int(seconds // 60)
        return f"{value} minute" + ("s" if value != 1 else "")
    value = int(seconds) if float(seconds).is_integer() else seconds
    return f"{value} second" + ("s" if value != 1 else "")


def _weather(location: str) -> dict:
    q = urlencode({"name": location[:120], "count": 1, "language": "en", "format": "json"})
    geo = utilities._fetch_json(f"https://geocoding-api.open-meteo.com/v1/search?{q}")
    results = geo.get("results") or []
    if not results:
        raise ValueError(f"Could not find location: {location}")
    place = results[0]
    params = urlencode({
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "auto",
        "forecast_days": 1,
    })
    data = utilities._fetch_json(f"https://api.open-meteo.com/v1/forecast?{params}")
    current = data.get("current", {})
    daily = data.get("daily", {})
    return {
        "type": "weather",
        "location": f"{place.get('name')}, {place.get('country', '')}".strip(", "),
        "temperature_c": current.get("temperature_2m"),
        "feels_like_c": current.get("apparent_temperature"),
        "weather_code": current.get("weather_code"),
        "wind_kmh": current.get("wind_speed_10m"),
        "high_c": (daily.get("temperature_2m_max") or [None])[0],
        "low_c": (daily.get("temperature_2m_min") or [None])[0],
        "rain_chance_percent": (daily.get("precipitation_probability_max") or [None])[0],
        "source": "Open-Meteo",
    }


def _stopwatch_card() -> dict:
    with utilities._STOPWATCH_LOCK:
        elapsed = utilities._STOPWATCH["elapsed"]
        running = utilities._STOPWATCH["running"]
        if running:
            elapsed += time.monotonic() - utilities._STOPWATCH["started_at"]
    return {
        "type": "stopwatch",
        "status": "running" if running else "paused",
        "elapsed_seconds": round(elapsed, 3),
        "client_started_at_ms": int(time.time() * 1000) if running else None,
    }


def _safe_calc(expression: str):
    tree = ast.parse(expression, mode="eval")
    return productivity._eval_math(tree)


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default


def try_local_command(message: str) -> dict | None:
    """Handle deterministic utility requests without calling an LLM."""
    text = " ".join(message.strip().split())
    lower = text.lower()

    if re.search(r"\b(set|start)\b.*\btimer\b", lower) or lower.startswith("timer for "):
        seconds = _duration_seconds(lower)
        if seconds is None:
            return None
        if seconds <= 0 or seconds > 7 * 24 * 3600:
            return {"message": "Timer must be between 1 second and 7 days.", "card": None}
        item = utilities._create_timer(seconds, "Timer", "timer")
        return {"message": f"Timer set for {_pretty_duration(seconds)}.", "card": {"type": "timer", "id": item["id"], "status": item["status"], "duration_seconds": seconds, "due_at": item["due_at"]}}

    alarm_match = re.search(r"\b(?:set\s+)?(?:an\s+)?alarm\b.*?\b(\d{1,2}):(\d{2})\b", lower)
    if alarm_match:
        hour, minute = map(int, alarm_match.groups())
        if hour > 23 or minute > 59:
            return {"message": "That alarm time is invalid. Use 24-hour time such as 14:30.", "card": None}
        now = datetime.now()
        due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if due <= now:
            due += timedelta(days=1)
        item = utilities._create_timer((due - now).total_seconds(), "Alarm", "alarm")
        return {"message": f"Alarm set for {due.strftime('%H:%M')}.", "card": {"type": "alarm", "id": item["id"], "status": item["status"], "due_at": item["due_at"], "display_time": due.strftime("%H:%M"), "display_date": due.strftime("%Y-%m-%d")}}

    if "start stopwatch" in lower or lower == "start the stopwatch":
        with utilities._STOPWATCH_LOCK:
            if not utilities._STOPWATCH["running"]:
                utilities._STOPWATCH["running"] = True
                utilities._STOPWATCH["started_at"] = time.monotonic()
        return {"message": "Stopwatch started.", "card": _stopwatch_card()}

    if any(phrase in lower for phrase in ("pause stopwatch", "stop stopwatch", "pause the stopwatch", "stop the stopwatch")):
        with utilities._STOPWATCH_LOCK:
            if utilities._STOPWATCH["running"]:
                utilities._STOPWATCH["elapsed"] += time.monotonic() - utilities._STOPWATCH["started_at"]
                utilities._STOPWATCH["running"] = False
                utilities._STOPWATCH["started_at"] = None
        return {"message": "Stopwatch paused.", "card": _stopwatch_card()}

    if "reset stopwatch" in lower or "reset the stopwatch" in lower:
        with utilities._STOPWATCH_LOCK:
            utilities._STOPWATCH.update({"running": False, "started_at": None, "elapsed": 0.0})
        return {"message": "Stopwatch reset.", "card": _stopwatch_card()}

    if any(phrase in lower for phrase in ("stopwatch status", "stopwatch time", "how long on the stopwatch")):
        return {"message": "Here’s your stopwatch.", "card": _stopwatch_card()}

    weather_match = re.search(r"\bweather\s+(?:in|for|at)\s+(.+?)[?.!]*$", text, re.IGNORECASE)
    if weather_match:
        location = weather_match.group(1).strip()
        try:
            card = _weather(location)
        except Exception as exc:
            return {"message": f"Weather lookup failed: {exc}", "card": None}
        return {"message": f"Here’s the weather in {card['location']}.", "card": card}

    cancel_match = re.search(r"\bcancel\s+(?:timer|alarm)\s+([\w-]+)", lower)
    if cancel_match:
        timer_id = cancel_match.group(1)
        with utilities._TIMER_LOCK:
            item = utilities._TIMERS.get(timer_id)
            if not item:
                return {"message": "Timer not found.", "card": None}
            item["status"] = "cancelled"
        return {"message": f"Cancelled {timer_id}.", "card": None}

    calc_match = re.match(r"^(?:calculate|what is|what's)\s+([0-9+\-*/().%\s]+)\??$", lower)
    if calc_match:
        try:
            value = _safe_calc(calc_match.group(1).strip())
            return {"message": f"The result is {value}.", "card": {"type": "calculation", "expression": calc_match.group(1).strip(), "result": value}}
        except Exception:
            return None

    reminder_match = re.search(r"\bremind me(?: to)?\s+(.+?)\s+in\s+(\d+(?:\.\d+)?)\s*(minutes?|mins?|hours?|hrs?)\b", text, re.IGNORECASE)
    if reminder_match:
        reminder_text = reminder_match.group(1).strip()
        value = float(reminder_match.group(2))
        unit = reminder_match.group(3).lower()
        minutes = value * 60 if unit.startswith(("hour", "hr")) else value
        items = _load_json(productivity.REMINDERS, [])
        now = datetime.now()
        item = {"id": str(uuid.uuid4())[:8], "text": reminder_text, "status": "scheduled", "created_at": now.isoformat(timespec="seconds"), "due_at": (now + timedelta(minutes=minutes)).isoformat(timespec="seconds"), "repeat_minutes": 0}
        items.append(item)
        productivity._save(productivity.REMINDERS, items)
        return {"message": f"Reminder set for {_pretty_duration(minutes * 60)} from now.", "card": {"type": "reminder", **item}}

    recurring_match = re.search(r"\bremind me(?: to)?\s+(.+?)\s+every\s+(\d+(?:\.\d+)?)\s*(minutes?|mins?|hours?|hrs?)\b", text, re.IGNORECASE)
    if recurring_match:
        reminder_text = recurring_match.group(1).strip()
        value = float(recurring_match.group(2))
        unit = recurring_match.group(3).lower()
        minutes = value * 60 if unit.startswith(("hour", "hr")) else value
        items = _load_json(productivity.REMINDERS, [])
        now = datetime.now()
        item = {"id": str(uuid.uuid4())[:8], "text": reminder_text, "status": "scheduled", "created_at": now.isoformat(timespec="seconds"), "due_at": (now + timedelta(minutes=minutes)).isoformat(timespec="seconds"), "repeat_minutes": minutes}
        items.append(item)
        productivity._save(productivity.REMINDERS, items)
        return {"message": f"Recurring reminder set for every {_pretty_duration(minutes * 60)}.", "card": {"type": "reminder", **item}}

    if lower in {"show reminders", "list reminders", "my reminders"}:
        items = _load_json(productivity.REMINDERS, [])
        return {"message": f"You have {len(items)} reminder(s).", "card": {"type": "reminders", "items": items}}

    note_match = re.match(r"^(?:save note|note)\s+([^:]+):\s*(.+)$", text, re.IGNORECASE)
    if note_match:
        title, content = note_match.group(1).strip(), note_match.group(2).strip()
        notes = _load_json(productivity.NOTES, {})
        notes[title[:120]] = {"content": content[:10000], "updated_at": datetime.now().isoformat(timespec="seconds")}
        productivity._save(productivity.NOTES, notes)
        return {"message": f"Saved note “{title}”.", "card": {"type": "note", "title": title, "content": content}}

    if lower in {"system status", "show system status", "agentie status"}:
        import platform, shutil, os
        disk = shutil.disk_usage(Path.cwd())
        card = {"type": "system", "os": platform.system(), "os_detail": platform.platform(), "python": platform.python_version(), "hostname": platform.node(), "disk_total_gb": round(disk.total / 1024**3, 1), "disk_free_gb": round(disk.free / 1024**3, 1), "process_id": os.getpid()}
        return {"message": "Here’s Agentie’s local system status.", "card": card}

    if lower in {"show tasks", "list tasks", "my tasks"}:
        items = _load_json(Path.cwd() / "workspace" / "tasks.json", [])
        return {"message": f"You have {len(items)} tracked task(s).", "card": {"type": "tasks", "items": items}}

    if lower in {"show approvals", "list approvals", "pending approvals"}:
        items = _load_json(Path.cwd() / "workspace" / "approvals.json", [])
        return {"message": f"There are {len(items)} approval request(s).", "card": {"type": "approvals", "items": items}}

    if lower in {"show files", "list files", "workspace files"}:
        workspace = Path.cwd() / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        items = [{"name": p.name, "size_bytes": p.stat().st_size, "suffix": p.suffix.lower()} for p in sorted(workspace.iterdir()) if p.is_file()]
        return {"message": f"There are {len(items)} file(s) in the workspace.", "card": {"type": "files", "items": items}}

    return None
