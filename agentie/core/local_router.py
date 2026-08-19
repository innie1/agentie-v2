import ast
import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timedelta
from difflib import get_close_matches
from pathlib import Path
from urllib.parse import quote, urlencode

from PIL import Image

from agentie.tools import advanced_utility_tools as advanced
from agentie.tools import local_utility_tools as utilities
from agentie.tools import productivity_tools as productivity

_DURATION_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>seconds?|secs?|minutes?|mins?|hours?|hrs?)",
    re.IGNORECASE,
)

_UNIT_ALIASES = {
    "kilometer": "km", "kilometers": "km", "km": "km",
    "mile": "mi", "miles": "mi", "mi": "mi",
    "meter": "m", "meters": "m", "m": "m",
    "foot": "ft", "feet": "ft", "ft": "ft",
    "kilogram": "kg", "kilograms": "kg", "kg": "kg",
    "pound": "lb", "pounds": "lb", "lb": "lb", "lbs": "lb",
    "celsius": "c", "c": "c", "fahrenheit": "f", "f": "f",
    "liter": "l", "liters": "l", "litre": "l", "litres": "l", "l": "l",
    "gallon": "gal", "gallons": "gal", "gal": "gal",
}

# Common misspellings and conversational aliases. This stays deliberately small;
# fuzzy matching is only used for high-confidence utility words.
_INTENT_WORDS = {
    "time", "clock", "weather", "forecast", "temperature", "timer", "alarm",
    "calculate", "calculator", "convert", "remind", "reminder", "note", "tasks",
    "status", "wikipedia", "wiki", "stopwatch", "scratchpad", "checksum",
}
_TYPO_ALIASES = {
    "wheather": "weather", "whether": "weather", "weathr": "weather",
    "tmer": "timer", "timr": "timer", "tiemr": "timer",
    "calclate": "calculate", "calcualte": "calculate", "calcuate": "calculate",
    "rember": "remind", "reminde": "remind", "remid": "remind",
    "wikipidia": "wikipedia", "wikpedia": "wikipedia",
    "stopwach": "stopwatch", "stopwath": "stopwatch",
}


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
        "latitude": place["latitude"], "longitude": place["longitude"],
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "auto", "forecast_days": 1,
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
        "type": "stopwatch", "status": "running" if running else "paused",
        "elapsed_seconds": round(elapsed, 3),
        "client_started_at_ms": int(time.time() * 1000) if running else None,
    }


def _safe_calc(expression: str):
    return productivity._eval_math(ast.parse(expression, mode="eval"))


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default


def _save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def _normalize_text(text: str) -> str:
    value = text.lower().replace("what's", "what is").replace("whats", "what is")
    value = re.sub(r"[^a-z0-9:.+*/%_\- ]+", " ", value)
    words = value.split()
    normalized = []
    for word in words:
        if word in _TYPO_ALIASES:
            normalized.append(_TYPO_ALIASES[word])
            continue
        # Only fuzzy-correct short command-like words. This avoids changing names/places.
        if 4 <= len(word) <= 11 and word.isalpha():
            match = get_close_matches(word, _INTENT_WORDS, n=1, cutoff=0.86)
            normalized.append(match[0] if match else word)
        else:
            normalized.append(word)
    return " ".join(normalized)


def _split_commands(text: str) -> list[str]:
    """Split obvious compound requests while preserving normal conversational wording."""
    normalized = re.sub(r"\s+", " ", text.strip())
    parts = re.split(r"\s*(?:[;]|\bthen\b)\s*", normalized, flags=re.IGNORECASE)
    expanded: list[str] = []
    command_start = (
        r"(?:calculate|calculator|convert|set|start|pause|stop|reset|remind|reminder|show|list|"
        r"what|tell|give|weather|wheather|forecast|temperature|wiki|wikipedia|look|rss|system|"
        r"countdown|sha256|checksum|image|inspect|scratchpad|note|save|cancel|time|clock)"
    )
    for part in parts:
        chunks = re.split(
            rf"\s*,\s*(?:and\s+)?(?={command_start}\b)|\s+and\s+(?={command_start}\b)",
            part,
            flags=re.IGNORECASE,
        )
        expanded.extend(chunk.strip(" .?!") for chunk in chunks if chunk.strip(" .?!"))
    return expanded


def _try_single_local_command(message: str) -> dict | None:
    text = " ".join(message.strip().split())
    lower = _normalize_text(text).strip(" .?!")

    # Natural time phrases: "time?", "tell me time", "hey what's the time now", "clock please".
    if (
        lower in {"time", "clock", "time now", "current time", "local time", "current local time"}
        or (re.search(r"\btime\b", lower) and re.search(r"\b(what|tell|give|current|now|local|please|hey|show)\b", lower))
        or re.search(r"\bwhat is the time\b", lower)
    ) and "timer" not in lower:
        now = datetime.now().astimezone()
        return {
            "message": f"It is {now.strftime('%H:%M:%S')} on {now.strftime('%Y-%m-%d')}.",
            "card": {"type": "datetime", "datetime": now.isoformat(timespec="seconds"), "timezone": str(now.tzinfo)},
        }

    calc_match = re.search(r"(?:calculate|calculator|calc|work out|solve)\s+([0-9+\-*/().%\s]+)$", lower)
    if calc_match:
        try:
            expression = calc_match.group(1).strip()
            value = _safe_calc(expression)
            return {"message": f"{expression} = {value}.", "card": {"type": "calculation", "expression": expression, "result": value}}
        except Exception:
            return None

    convert_match = re.search(r"(?:convert\s+)?(-?\d+(?:\.\d+)?)\s+([a-z]+)\s+(?:to|into|in)\s+([a-z]+)$", lower)
    if convert_match and ("convert" in lower or convert_match.group(2) in _UNIT_ALIASES):
        value = float(convert_match.group(1))
        source_raw, target_raw = convert_match.group(2), convert_match.group(3)
        source, target = _UNIT_ALIASES.get(source_raw), _UNIT_ALIASES.get(target_raw)
        if source and target:
            fn = productivity._CONVERSIONS.get((source, target))
            if fn:
                result = fn(value)
                return {
                    "message": f"{value:g} {source_raw} = {result:.6g} {target_raw}.",
                    "card": {"type": "unit_conversion", "value": value, "from_unit": source_raw, "to_unit": target_raw, "result": result},
                }

    if ("timer" in lower and re.search(r"\b(set|start|give|make|for)\b", lower)) or lower.startswith("timer "):
        seconds = _duration_seconds(lower)
        if seconds is None:
            return None
        if seconds <= 0 or seconds > 7 * 24 * 3600:
            return {"message": "Timer must be between 1 second and 7 days.", "card": None}
        item = utilities._create_timer(seconds, "Timer", "timer")
        return {
            "message": f"Timer set for {_pretty_duration(seconds)}.",
            "card": {"type": "timer", "id": item["id"], "status": item["status"], "duration_seconds": seconds, "due_at": item["due_at"]},
        }

    alarm_match = re.search(r"\balarm\b.*?\b(\d{1,2}):(\d{2})\b", lower)
    if alarm_match:
        hour, minute = map(int, alarm_match.groups())
        if hour > 23 or minute > 59:
            return {"message": "That alarm time is invalid. Use 24-hour time such as 14:30.", "card": None}
        now = datetime.now()
        due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if due <= now:
            due += timedelta(days=1)
        item = utilities._create_timer((due - now).total_seconds(), "Alarm", "alarm")
        return {
            "message": f"Alarm set for {due.strftime('%H:%M')}.",
            "card": {"type": "alarm", "id": item["id"], "status": item["status"], "due_at": item["due_at"], "display_time": due.strftime("%H:%M"), "display_date": due.strftime("%Y-%m-%d")},
        }

    reminder_match = re.search(r"\b(?:remind|reminder)(?: me)?(?: to)?\s+(.+?)\s+in\s+(\d+(?:\.\d+)?)\s*(minutes?|mins?|hours?|hrs?)\b", lower, re.IGNORECASE)
    if reminder_match:
        reminder_text = reminder_match.group(1).strip()
        value = float(reminder_match.group(2)); unit = reminder_match.group(3).lower()
        minutes = value * 60 if unit.startswith(("hour", "hr")) else value
        items = _load_json(productivity.REMINDERS, []); now = datetime.now()
        item = {
            "id": str(uuid.uuid4())[:8], "text": reminder_text, "status": "scheduled",
            "created_at": now.isoformat(timespec="seconds"),
            "due_at": (now + timedelta(minutes=minutes)).isoformat(timespec="seconds"), "repeat_minutes": 0,
        }
        items.append(item); productivity._save(productivity.REMINDERS, items)
        return {"message": f"Reminder set for {_pretty_duration(minutes * 60)} from now.", "card": {"type": "reminder", **item}}

    recurring_match = re.search(r"\b(?:remind|reminder)(?: me)?(?: to)?\s+(.+?)\s+every\s+(\d+(?:\.\d+)?)\s*(minutes?|mins?|hours?|hrs?)\b", lower, re.IGNORECASE)
    if recurring_match:
        reminder_text = recurring_match.group(1).strip(); value = float(recurring_match.group(2)); unit = recurring_match.group(3).lower()
        minutes = value * 60 if unit.startswith(("hour", "hr")) else value
        items = _load_json(productivity.REMINDERS, []); now = datetime.now()
        item = {
            "id": str(uuid.uuid4())[:8], "text": reminder_text, "status": "scheduled",
            "created_at": now.isoformat(timespec="seconds"),
            "due_at": (now + timedelta(minutes=minutes)).isoformat(timespec="seconds"), "repeat_minutes": minutes,
        }
        items.append(item); productivity._save(productivity.REMINDERS, items)
        return {"message": f"Recurring reminder set for every {_pretty_duration(minutes * 60)}.", "card": {"type": "reminder", **item}}

    weekday_match = re.search(r"\b(?:remind|reminder)(?: me)?(?: to)?\s+(.+?)\s+every weekday(?: at\s+(\d{1,2}:\d{2}))?\b", lower, re.IGNORECASE)
    if weekday_match:
        items = _load_json(advanced.SCHEDULES, [])
        item = {
            "id": str(uuid.uuid4())[:8], "text": weekday_match.group(1).strip(), "cadence": "weekdays",
            "time_hhmm": weekday_match.group(2) or "09:00", "status": "active",
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        items.append(item); _save_json(advanced.SCHEDULES, items)
        return {"message": f"Recurring weekday reminder set for {item['time_hhmm']}.", "card": {"type": "schedule", **item}}

    if "start stopwatch" in lower or "start the stopwatch" in lower:
        with utilities._STOPWATCH_LOCK:
            if not utilities._STOPWATCH["running"]:
                utilities._STOPWATCH["running"] = True; utilities._STOPWATCH["started_at"] = time.monotonic()
        return {"message": "Stopwatch started.", "card": _stopwatch_card()}

    if re.search(r"\b(pause|stop)\b.*\bstopwatch\b", lower):
        with utilities._STOPWATCH_LOCK:
            if utilities._STOPWATCH["running"]:
                utilities._STOPWATCH["elapsed"] += time.monotonic() - utilities._STOPWATCH["started_at"]
                utilities._STOPWATCH["running"] = False; utilities._STOPWATCH["started_at"] = None
        return {"message": "Stopwatch paused.", "card": _stopwatch_card()}

    if re.search(r"\breset\b.*\bstopwatch\b", lower):
        with utilities._STOPWATCH_LOCK:
            utilities._STOPWATCH.update({"running": False, "started_at": None, "elapsed": 0.0})
        return {"message": "Stopwatch reset.", "card": _stopwatch_card()}

    weather_match = re.search(r"\b(?:weather|forecast|temperature)\b(?:\s+(?:in|for|at))?\s+(.+?)$", lower)
    if weather_match:
        location = weather_match.group(1).strip()
        location = re.sub(r"^(?:please|now)\s+", "", location).strip()
        if location:
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
            if not item: return {"message": "Timer not found.", "card": None}
            item["status"] = "cancelled"
        return {"message": f"Cancelled {timer_id}.", "card": None}

    if re.search(r"\b(show|list|my)\b.*\breminders?\b", lower):
        items = _load_json(productivity.REMINDERS, [])
        return {"message": f"You have {len(items)} reminder(s).", "card": {"type": "reminders", "items": items}}

    if re.search(r"\b(show|list|my)\b.*\bschedules?\b", lower) or lower == "recurring reminders":
        items = _load_json(advanced.SCHEDULES, [])
        return {"message": f"You have {len(items)} recurring schedule(s).", "card": {"type": "schedules", "items": items}}

    # Accept both "note Title: text" and conversational "save a note called Title with the text ...".
    note_match = re.match(r"^(?:save (?:a )?note|note)\s+([^:]+):\s*(.+)$", text, re.IGNORECASE)
    if not note_match:
        note_match = re.match(r"^save (?:a )?note called\s+(.+?)\s+with (?:the )?text\s+[\"“]?(.+?)[\"”]?$", text, re.IGNORECASE)
    if note_match:
        title, content = note_match.group(1).strip(' \"“”'), note_match.group(2).strip(' \"“”')
        notes = _load_json(productivity.NOTES, {})
        notes[title[:120]] = {"content": content[:10000], "updated_at": datetime.now().isoformat(timespec="seconds")}
        productivity._save(productivity.NOTES, notes)
        return {"message": f"Saved note “{title}”.", "card": {"type": "note", "title": title, "content": content}}

    scratch_match = re.match(r"^(?:scratchpad|remember temporarily)\s+([^:]+):\s*(.+)$", text, re.IGNORECASE)
    if scratch_match:
        data = _load_json(advanced.SCRATCHPAD, {}); key, value = scratch_match.group(1).strip(), scratch_match.group(2).strip()
        data[key] = value; _save_json(advanced.SCRATCHPAD, data)
        return {"message": f"Saved “{key}” to the scratchpad.", "card": {"type": "scratchpad", "key": key, "value": value}}

    countdown_match = re.match(r"^(?:countdown to|how long until)\s+(\d{4}-\d{2}-\d{2}(?:[ t]\d{2}:\d{2}(?::\d{2})?)?)$", lower)
    if countdown_match:
        target = datetime.fromisoformat(countdown_match.group(1).replace(" ", "T")); seconds = (target - datetime.now()).total_seconds()
        return {"message": f"There are {_pretty_duration(abs(seconds))} {'remaining' if seconds >= 0 else 'since that time'}.", "card": {"type": "countdown", "target": target.isoformat(), "remaining_seconds": seconds}}

    checksum_match = re.match(r"^(?:sha256|checksum)(?: of)?\s+(.+)$", text, re.IGNORECASE)
    if checksum_match:
        target = advanced._safe_path(checksum_match.group(1).strip())
        if not target.exists() or not target.is_file(): return {"message": "File not found.", "card": None}
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        return {"message": f"SHA-256 calculated for {target.name}.", "card": {"type": "checksum", "filename": target.name, "algorithm": "sha256", "checksum": digest}}

    image_match = re.match(r"^(?:image metadata|inspect image)\s+(.+)$", text, re.IGNORECASE)
    if image_match:
        target = advanced._safe_path(image_match.group(1).strip())
        try:
            with Image.open(target) as image:
                card = {"type": "image_metadata", "filename": target.name, "format": image.format, "width": image.width, "height": image.height, "mode": image.mode, "size_bytes": target.stat().st_size}
        except Exception as exc: return {"message": f"Could not inspect image: {exc}", "card": None}
        return {"message": f"Here’s the metadata for {target.name}.", "card": card}

    wiki_match = re.match(r"^(?:wikipedia|wiki)(?: lookup| search)?\s+(.+)$", lower)
    if not wiki_match:
        wiki_match = re.match(r"^(?:look up|lookup|search)\s+(?:on\s+)?wikipedia(?:\s+(?:for|about))?\s+(.+)$", lower)
    if wiki_match:
        topic = wiki_match.group(1).strip()
        try:
            raw = advanced._fetch_text(f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(topic.replace(' ', '_'), safe='')}")
            data = json.loads(raw)
        except Exception as exc: return {"message": f"Wikipedia lookup failed: {exc}", "card": None}
        card = {"type": "wikipedia", "title": data.get("title"), "description": data.get("description"), "extract": data.get("extract"), "url": ((data.get("content_urls") or {}).get("desktop") or {}).get("page")}
        return {"message": f"Here’s the Wikipedia summary for {card['title'] or topic}.", "card": card}

    rss_match = re.match(r"^(?:read rss|rss)\s+(https?://\S+)$", text, re.IGNORECASE)
    if rss_match:
        try:
            xml = advanced._fetch_text(rss_match.group(1)); from xml.etree import ElementTree
            root = ElementTree.fromstring(xml); items = []
            for item in root.findall('.//item')[:10]:
                items.append({"title": (item.findtext('title') or '').strip(), "link": (item.findtext('link') or '').strip(), "published": (item.findtext('pubDate') or '').strip()})
        except Exception as exc: return {"message": f"RSS read failed: {exc}", "card": None}
        return {"message": f"Loaded {len(items)} RSS item(s).", "card": {"type": "rss", "items": items}}

    if re.search(r"\b(system|agentie)\b.*\bstatus\b", lower) or re.search(r"\bstatus\b.*\b(system|agentie)\b", lower):
        import os, platform, shutil, psutil
        disk = shutil.disk_usage(Path.cwd()); mem = psutil.virtual_memory()
        card = {"type": "system", "os": platform.system(), "os_detail": platform.platform(), "python": platform.python_version(), "hostname": platform.node(), "cpu_percent": psutil.cpu_percent(interval=0.05), "memory_percent": mem.percent, "memory_available_gb": round(mem.available / 1024**3, 2), "disk_total_gb": round(disk.total / 1024**3, 1), "disk_free_gb": round(disk.free / 1024**3, 1), "process_id": os.getpid()}
        return {"message": "Here’s Agentie’s local system status.", "card": card}

    if re.search(r"\b(show|list|my|task)\b.*\btasks?\b", lower) or lower in {"task progress", "show task progress"}:
        items = _load_json(Path.cwd() / "workspace" / "tasks.json", [])
        total = sum(len(t.get("steps", [])) for t in items)
        done = sum(sum(1 for s in t.get("steps", []) if s.get("done")) for t in items)
        ctype = "agent_progress" if "progress" in lower else "tasks"
        return {"message": f"You have {len(items)} tracked task(s).", "card": {"type": ctype, "items": items, "completed_steps": done, "total_steps": total}}

    if re.search(r"\b(show|list|pending)\b.*\bapprovals?\b", lower):
        items = _load_json(Path.cwd() / "workspace" / "approvals.json", [])
        return {"message": f"There are {len(items)} approval request(s).", "card": {"type": "approvals", "items": items}}

    if re.search(r"\b(show|list|workspace)\b.*\bfiles?\b", lower):
        workspace = Path.cwd() / "workspace"; workspace.mkdir(parents=True, exist_ok=True)
        items = [{"name": p.name, "size_bytes": p.stat().st_size, "suffix": p.suffix.lower()} for p in sorted(workspace.iterdir()) if p.is_file()]
        return {"message": f"There are {len(items)} file(s) in the workspace.", "card": {"type": "files", "items": items}}

    return None


def route_local_actions(message: str) -> dict:
    """Return local results plus unresolved clauses; never discard recognized work."""
    from agentie.core.advanced_local_router import try_advanced_local_command

    parts = _split_commands(message)
    results: list[dict] = []
    unresolved: list[str] = []
    for part in parts:
        result = try_advanced_local_command(part)
        if result is None:
            result = _try_single_local_command(part)
        if result is None:
            unresolved.append(part)
        else:
            results.append(result)
    return {"results": results, "unresolved": unresolved}


def try_local_command(message: str) -> dict | None:
    """Compatibility wrapper for callers that only want fully local execution."""
    routed = route_local_actions(message)
    results, unresolved = routed["results"], routed["unresolved"]
    if unresolved:
        return None
    if not results:
        return None
    if len(results) == 1:
        return results[0]
    return {
        "message": "",
        "card": {"type": "multi", "items": [{"message": r.get("message", ""), "card": r.get("card")} for r in results]},
    }
