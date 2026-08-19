import json
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode

from agentie.tools import local_utility_tools as utilities


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
        "location": f"{place.get('name')}, {place.get('country', '')}".strip(", "),
        "temperature_c": current.get("temperature_2m"),
        "feels_like_c": current.get("apparent_temperature"),
        "wind_kmh": current.get("wind_speed_10m"),
        "high_c": (daily.get("temperature_2m_max") or [None])[0],
        "low_c": (daily.get("temperature_2m_min") or [None])[0],
        "rain_chance_percent": (daily.get("precipitation_probability_max") or [None])[0],
    }


def try_local_command(message: str) -> str | None:
    """Handle deterministic utility requests without calling an LLM.

    Returns None when the request is not confidently recognized as a local command.
    """
    text = " ".join(message.strip().split())
    lower = text.lower()

    if re.search(r"\b(set|start)\b.*\btimer\b", lower) or lower.startswith("timer for "):
        seconds = _duration_seconds(lower)
        if seconds is None:
            return None
        if seconds <= 0 or seconds > 7 * 24 * 3600:
            return "Timer must be between 1 second and 7 days."
        item = utilities._create_timer(seconds, "Timer", "timer")
        return f"Timer set for {seconds:g} seconds. ID: {item['id']}."

    alarm_match = re.search(r"\b(?:set\s+)?(?:an\s+)?alarm\b.*?\b(\d{1,2}):(\d{2})\b", lower)
    if alarm_match:
        hour, minute = map(int, alarm_match.groups())
        if hour > 23 or minute > 59:
            return "That alarm time is invalid. Use 24-hour time such as 14:30."
        now = datetime.now()
        due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if due <= now:
            due += timedelta(days=1)
        item = utilities._create_timer((due - now).total_seconds(), "Alarm", "alarm")
        return f"Alarm set for {due.strftime('%Y-%m-%d %H:%M')}. ID: {item['id']}."

    if "start stopwatch" in lower or lower == "start the stopwatch":
        with utilities._STOPWATCH_LOCK:
            if utilities._STOPWATCH["running"]:
                return "Stopwatch is already running."
            utilities._STOPWATCH["running"] = True
            utilities._STOPWATCH["started_at"] = time.monotonic()
        return "Stopwatch started."

    if any(phrase in lower for phrase in ("pause stopwatch", "stop stopwatch", "pause the stopwatch", "stop the stopwatch")):
        with utilities._STOPWATCH_LOCK:
            if utilities._STOPWATCH["running"]:
                utilities._STOPWATCH["elapsed"] += time.monotonic() - utilities._STOPWATCH["started_at"]
                utilities._STOPWATCH["running"] = False
                utilities._STOPWATCH["started_at"] = None
            elapsed = utilities._STOPWATCH["elapsed"]
        return f"Stopwatch paused at {elapsed:.2f} seconds."

    if "reset stopwatch" in lower or "reset the stopwatch" in lower:
        with utilities._STOPWATCH_LOCK:
            utilities._STOPWATCH.update({"running": False, "started_at": None, "elapsed": 0.0})
        return "Stopwatch reset."

    if any(phrase in lower for phrase in ("stopwatch status", "stopwatch time", "how long on the stopwatch")):
        with utilities._STOPWATCH_LOCK:
            elapsed = utilities._STOPWATCH["elapsed"]
            if utilities._STOPWATCH["running"]:
                elapsed += time.monotonic() - utilities._STOPWATCH["started_at"]
            running = utilities._STOPWATCH["running"]
        return f"Stopwatch: {elapsed:.2f} seconds; running={running}."

    weather_match = re.search(r"\bweather\s+(?:in|for|at)\s+(.+?)[?.!]*$", text, re.IGNORECASE)
    if weather_match:
        location = weather_match.group(1).strip()
        try:
            data = _weather(location)
        except Exception as exc:
            return f"Weather lookup failed: {exc}"
        summary = (
            f"{data['location']}: {data['temperature_c']}°C, feels like {data['feels_like_c']}°C. "
            f"High {data['high_c']}°C, low {data['low_c']}°C, rain chance {data['rain_chance_percent']}%."
        )
        utilities._popup("Agentie Weather", summary)
        return summary + " Source: Open-Meteo (no API key)."

    return None
