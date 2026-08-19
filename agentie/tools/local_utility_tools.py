import json
import re
import threading
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from agents import function_tool


_TIMER_LOCK = threading.Lock()
_TIMERS: dict[str, dict] = {}
_STOPWATCH = {"running": False, "started_at": None, "elapsed": 0.0}
_STOPWATCH_LOCK = threading.Lock()


def _run_timer(timer_id: str, seconds: float, label: str) -> None:
    """Advance timer state in the background without OS-level notifications."""
    time.sleep(max(0.0, seconds))
    with _TIMER_LOCK:
        item = _TIMERS.get(timer_id)
        if not item or item.get("status") != "running":
            return
        item["status"] = "finished"
        item["finished_at"] = datetime.now().isoformat(timespec="seconds")


def _create_timer(seconds: float, label: str, kind: str = "timer") -> dict:
    timer_id = f"{kind}-{int(time.time() * 1000)}"
    now = datetime.now()
    item = {
        "id": timer_id,
        "kind": kind,
        "label": label,
        "status": "running",
        "seconds": round(seconds, 3),
        "created_at": now.isoformat(timespec="seconds"),
        "due_at": (now + timedelta(seconds=seconds)).isoformat(timespec="seconds"),
    }
    with _TIMER_LOCK:
        _TIMERS[timer_id] = item
    threading.Thread(target=_run_timer, args=(timer_id, seconds, label), daemon=True).start()
    return item


@function_tool
def set_timer(seconds: float, label: str = "Timer") -> str:
    """Set a local in-process timer for rendering in Agentie's chat UI."""
    if seconds <= 0 or seconds > 7 * 24 * 3600:
        raise ValueError("Timer must be between 1 second and 7 days.")
    return json.dumps(_create_timer(seconds, label, "timer"))


@function_tool
def set_alarm_at(local_time_hhmm: str, label: str = "Alarm") -> str:
    """Set a local alarm for the next occurrence of HH:MM using the computer's local time."""
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", local_time_hhmm.strip())
    if not match:
        raise ValueError("Use HH:MM, for example 14:30.")
    hour, minute = map(int, match.groups())
    if hour > 23 or minute > 59:
        raise ValueError("Invalid time.")
    now = datetime.now()
    due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if due <= now:
        due += timedelta(days=1)
    seconds = (due - now).total_seconds()
    return json.dumps(_create_timer(seconds, label, "alarm"))


@function_tool
def list_timers() -> str:
    """List local timers and alarms created during the current Agentie server session."""
    with _TIMER_LOCK:
        return json.dumps(list(_TIMERS.values()), indent=2)


@function_tool
def cancel_timer(timer_id: str) -> str:
    """Cancel a local timer or alarm by ID."""
    with _TIMER_LOCK:
        item = _TIMERS.get(timer_id)
        if not item:
            return "Timer not found."
        if item.get("status") != "running":
            return f"Timer is already {item.get('status')}."
        item["status"] = "cancelled"
    return f"Cancelled {timer_id}."


@function_tool
def stopwatch_start() -> str:
    """Start or resume the local stopwatch."""
    with _STOPWATCH_LOCK:
        if _STOPWATCH["running"]:
            return "Stopwatch is already running."
        _STOPWATCH["running"] = True
        _STOPWATCH["started_at"] = time.monotonic()
        return "Stopwatch started."


@function_tool
def stopwatch_pause() -> str:
    """Pause the local stopwatch and return elapsed seconds."""
    with _STOPWATCH_LOCK:
        if _STOPWATCH["running"]:
            _STOPWATCH["elapsed"] += time.monotonic() - _STOPWATCH["started_at"]
            _STOPWATCH["running"] = False
            _STOPWATCH["started_at"] = None
        return f"Elapsed: {_STOPWATCH['elapsed']:.2f} seconds."


@function_tool
def stopwatch_reset() -> str:
    """Reset the local stopwatch to zero."""
    with _STOPWATCH_LOCK:
        _STOPWATCH.update({"running": False, "started_at": None, "elapsed": 0.0})
    return "Stopwatch reset."


@function_tool
def stopwatch_status() -> str:
    """Return current stopwatch elapsed time."""
    with _STOPWATCH_LOCK:
        elapsed = _STOPWATCH["elapsed"]
        if _STOPWATCH["running"]:
            elapsed += time.monotonic() - _STOPWATCH["started_at"]
        return f"Elapsed: {elapsed:.2f} seconds; running={_STOPWATCH['running']}."


@function_tool
def show_notification(title: str, message: str) -> str:
    """Return notification text for the Agentie UI instead of creating an OS popup."""
    return f"{title[:80]}: {message[:500]}"


def _fetch_json(url: str) -> dict:
    req = Request(url, headers={"User-Agent": "Agentie/0.5"})
    with urlopen(req, timeout=10) as response:
        return json.loads(response.read(500_000).decode("utf-8"))


@function_tool
def weather_lookup(location: str) -> str:
    """Get current weather and today's forecast from Open-Meteo without an API key."""
    q = urlencode({"name": location[:120], "count": 1, "language": "en", "format": "json"})
    geo = _fetch_json(f"https://geocoding-api.open-meteo.com/v1/search?{q}")
    results = geo.get("results") or []
    if not results:
        return f"Could not find location: {location}"
    place = results[0]
    params = urlencode({
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "auto",
        "forecast_days": 1,
    })
    data = _fetch_json(f"https://api.open-meteo.com/v1/forecast?{params}")
    current = data.get("current", {})
    daily = data.get("daily", {})
    result = {
        "location": f"{place.get('name')}, {place.get('country', '')}".strip(", "),
        "temperature_c": current.get("temperature_2m"),
        "feels_like_c": current.get("apparent_temperature"),
        "wind_kmh": current.get("wind_speed_10m"),
        "weather_code": current.get("weather_code"),
        "high_c": (daily.get("temperature_2m_max") or [None])[0],
        "low_c": (daily.get("temperature_2m_min") or [None])[0],
        "rain_chance_percent": (daily.get("precipitation_probability_max") or [None])[0],
        "source": "Open-Meteo",
    }
    return json.dumps(result)
