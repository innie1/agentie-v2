import hashlib
import json
import os
import platform
import shutil
import uuid
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

import yaml
from PIL import Image
from agents import function_tool

WORKSPACE = Path.cwd() / "workspace"
SCRATCHPAD = WORKSPACE / "scratchpad.json"
SCHEDULES = WORKSPACE / "schedules.json"
MAX_FILE_BYTES = 25 * 1024 * 1024


def _safe_path(filename: str) -> Path:
    name = Path(filename).name.strip()
    if not name or name in {".", ".."}:
        raise ValueError("A valid workspace filename is required.")
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    return WORKSPACE / name


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


@function_tool
def local_datetime() -> str:
    """Return the computer's current local date and time without an external API."""
    now = datetime.now().astimezone()
    return json.dumps({
        "local_datetime": now.isoformat(timespec="seconds"),
        "date": now.date().isoformat(),
        "time": now.strftime("%H:%M:%S"),
        "timezone": str(now.tzinfo),
        "utc_offset": now.strftime("%z"),
    })


@function_tool
def date_difference(start_iso: str, end_iso: str) -> str:
    """Calculate the time difference between two ISO dates or datetimes locally."""
    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)
    delta = end - start
    seconds = delta.total_seconds()
    return json.dumps({
        "seconds": seconds,
        "minutes": seconds / 60,
        "hours": seconds / 3600,
        "days": seconds / 86400,
    })


@function_tool
def countdown_to(target_iso: str) -> str:
    """Calculate a countdown from now to an ISO local datetime."""
    target = datetime.fromisoformat(target_iso)
    now = datetime.now(target.tzinfo) if target.tzinfo else datetime.now()
    seconds = (target - now).total_seconds()
    return json.dumps({"target": target.isoformat(), "remaining_seconds": seconds})


@function_tool
def create_recurring_schedule(text: str, cadence: str, time_hhmm: str = "") -> str:
    """Create a persistent recurring schedule.

    cadence supports values such as `every 30 minutes`, `daily`, `weekdays`,
    `weekly monday`, or `weekly friday`. Optional time_hhmm uses 24-hour HH:MM.
    """
    cadence_clean = " ".join(cadence.lower().split())[:120]
    allowed_simple = {"daily", "weekdays"}
    valid = cadence_clean in allowed_simple or cadence_clean.startswith("every ") or cadence_clean.startswith("weekly ")
    if not valid:
        raise ValueError("Unsupported cadence. Use every N minutes/hours, daily, weekdays, or weekly <day>.")
    if time_hhmm:
        try:
            datetime.strptime(time_hhmm, "%H:%M")
        except ValueError as exc:
            raise ValueError("time_hhmm must be HH:MM, for example 09:00.") from exc
    items = _load_json(SCHEDULES, [])
    item = {
        "id": str(uuid.uuid4())[:8],
        "text": text[:500],
        "cadence": cadence_clean,
        "time_hhmm": time_hhmm,
        "status": "active",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    items.append(item)
    _save_json(SCHEDULES, items)
    return json.dumps(item)


@function_tool
def list_recurring_schedules() -> str:
    """List persistent recurring schedules."""
    return json.dumps(_load_json(SCHEDULES, []), indent=2)


@function_tool
def cancel_recurring_schedule(schedule_id: str) -> str:
    """Cancel a recurring schedule by ID."""
    items = _load_json(SCHEDULES, [])
    for item in items:
        if item.get("id") == schedule_id:
            item["status"] = "cancelled"
            _save_json(SCHEDULES, items)
            return f"Cancelled schedule {schedule_id}."
    return "Schedule not found."


@function_tool
def scratchpad_set(key: str, value: str) -> str:
    """Store a temporary scratchpad value for Agentie inside the local workspace."""
    data = _load_json(SCRATCHPAD, {})
    data[key[:120]] = value[:20000]
    _save_json(SCRATCHPAD, data)
    return f"Scratchpad saved: {key[:120]}"


@function_tool
def scratchpad_get(key: str) -> str:
    """Read a scratchpad value."""
    return str(_load_json(SCRATCHPAD, {}).get(key, "Scratchpad key not found."))


@function_tool
def scratchpad_list() -> str:
    """List scratchpad keys."""
    return json.dumps(sorted(_load_json(SCRATCHPAD, {}).keys()))


@function_tool
def zip_workspace_files(zip_filename: str, filenames: list[str]) -> str:
    """Create a ZIP archive from named files inside Agentie's workspace only."""
    target = _safe_path(zip_filename)
    if target.suffix.lower() != ".zip":
        raise ValueError("zip_filename must end with .zip")
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename in filenames[:100]:
            source = _safe_path(filename)
            if source.exists() and source.is_file() and source != target:
                archive.write(source, arcname=source.name)
    return f"Created archive: {target.name}"


@function_tool
def unzip_workspace_archive(zip_filename: str) -> str:
    """Extract a ZIP archive safely into workspace/extracted_<name>."""
    source = _safe_path(zip_filename)
    if not source.exists() or not zipfile.is_zipfile(source):
        raise ValueError("A valid workspace ZIP archive is required.")
    destination = WORKSPACE / f"extracted_{source.stem}"
    destination.mkdir(parents=True, exist_ok=True)
    extracted = []
    with zipfile.ZipFile(source) as archive:
        for member in archive.infolist()[:200]:
            candidate = (destination / member.filename).resolve()
            if destination.resolve() not in candidate.parents and candidate != destination.resolve():
                continue
            archive.extract(member, destination)
            extracted.append(member.filename)
    return json.dumps({"destination": str(destination), "files": extracted})


@function_tool
def format_json_text(text: str) -> str:
    """Validate and pretty-format JSON locally."""
    return json.dumps(json.loads(text), indent=2, ensure_ascii=False, sort_keys=True)


@function_tool
def format_yaml_text(text: str) -> str:
    """Validate and pretty-format YAML locally."""
    data = yaml.safe_load(text)
    return yaml.safe_dump(data, sort_keys=True, allow_unicode=True)


@function_tool
def compare_json_text(left: str, right: str) -> str:
    """Compare two JSON documents structurally."""
    a = json.loads(left)
    b = json.loads(right)
    return json.dumps({"equal": a == b, "left": a, "right": b}, indent=2, ensure_ascii=False)


@function_tool
def file_checksum(filename: str, algorithm: str = "sha256") -> str:
    """Calculate a checksum for a workspace file. Supports sha256, sha1, and md5."""
    if algorithm not in {"sha256", "sha1", "md5"}:
        raise ValueError("Supported algorithms: sha256, sha1, md5.")
    target = _safe_path(filename)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(filename)
    if target.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("File is too large for the local checksum tool.")
    digest = hashlib.new(algorithm)
    with target.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return json.dumps({"filename": target.name, "algorithm": algorithm, "checksum": digest.hexdigest()})


@function_tool
def image_metadata(filename: str) -> str:
    """Read basic image metadata for an image inside Agentie's workspace."""
    target = _safe_path(filename)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(filename)
    with Image.open(target) as image:
        data = {
            "filename": target.name,
            "format": image.format,
            "width": image.width,
            "height": image.height,
            "mode": image.mode,
            "file_size_bytes": target.stat().st_size,
        }
    return json.dumps(data)


def _fetch_text(url: str, max_bytes: int = 500_000) -> str:
    req = Request(url, headers={"User-Agent": "Agentie/0.7"})
    with urlopen(req, timeout=12) as response:
        return response.read(max_bytes).decode("utf-8", errors="replace")


@function_tool
def rss_read(feed_url: str, limit: int = 10) -> str:
    """Read a public RSS/Atom feed without a paid API."""
    if not feed_url.startswith(("http://", "https://")):
        raise ValueError("RSS URL must use http or https.")
    xml = _fetch_text(feed_url)
    root = ElementTree.fromstring(xml)
    items = []
    for item in root.findall(".//item")[:max(1, min(limit, 20))]:
        items.append({
            "title": (item.findtext("title") or "").strip(),
            "link": (item.findtext("link") or "").strip(),
            "published": (item.findtext("pubDate") or "").strip(),
        })
    if not items:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//a:entry", ns)[:max(1, min(limit, 20))]:
            link = entry.find("a:link", ns)
            items.append({
                "title": (entry.findtext("a:title", default="", namespaces=ns) or "").strip(),
                "link": link.attrib.get("href", "") if link is not None else "",
                "published": (entry.findtext("a:updated", default="", namespaces=ns) or "").strip(),
            })
    return json.dumps(items, ensure_ascii=False, indent=2)


@function_tool
def wikipedia_lookup(topic: str) -> str:
    """Look up a topic on Wikipedia using its free public REST endpoint."""
    title = quote(topic.strip().replace(" ", "_"), safe="")
    if not title:
        raise ValueError("A Wikipedia topic is required.")
    raw = _fetch_text(f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}")
    data = json.loads(raw)
    return json.dumps({
        "title": data.get("title"),
        "description": data.get("description"),
        "extract": data.get("extract"),
        "url": ((data.get("content_urls") or {}).get("desktop") or {}).get("page"),
    }, ensure_ascii=False)


@function_tool
def detailed_system_status() -> str:
    """Return CPU, memory, disk, Python, and Agentie runtime status locally."""
    import psutil

    disk = shutil.disk_usage(Path.cwd())
    memory = psutil.virtual_memory()
    data = {
        "os": platform.platform(),
        "python": platform.python_version(),
        "hostname": platform.node(),
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "cpu_count": os.cpu_count(),
        "memory_total_gb": round(memory.total / 1024**3, 2),
        "memory_available_gb": round(memory.available / 1024**3, 2),
        "memory_percent": memory.percent,
        "disk_total_gb": round(disk.total / 1024**3, 2),
        "disk_free_gb": round(disk.free / 1024**3, 2),
        "process_id": os.getpid(),
        "server_status": "running",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    return json.dumps(data)
