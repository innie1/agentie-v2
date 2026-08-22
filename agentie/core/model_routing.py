from __future__ import annotations

import json
import os
import re
import socket
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

WORKSPACE = Path(__file__).resolve().parents[2] / "workspace"
ROUTING_FILE = WORKSPACE / "model_routing.json"
VALID_MODES = {"local", "auto", "powerful"}
DEFAULT_MODE = "auto"
DEFAULT_LOCAL_MODEL = "gemma4"
DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:11434/v1"
_STATUS_CACHE: dict[str, object] = {"at": 0.0, "value": None}
_STATUS_LOCK = threading.Lock()

_POWERFUL_PATTERNS: tuple[tuple[str, int, str], ...] = (
    (r"\b(?:commit|push|merge|pull request|repo(?:sitory)?|refactor|debug|implement|codebase)\b", 2, "coding_or_repo"),
    (r"\b(?:send|email|post|publish|delete|remove|pay|payment|purchase|buy|transfer|refund|cancel subscription)\b", 2, "consequential_action"),
    (r"\b(?:deep research|research thoroughly|comprehensive research|latest|current|today|news|browse the web|search the web)\b", 2, "live_or_deep_research"),
    (r"\b(?:multi[- ]step|step by step and execute|coordinate|delegate|across agents|across apps|workflow)\b", 2, "multi_step_coordination"),
    (r"\b(?:analy[sz]e|compare|evaluate|strategy|plan|architecture|design)\b.{0,80}\b(?:risks?|tradeoffs?|alternatives?|recommendation)\b", 1, "complex_judgment"),
    (r"\b(?:spreadsheet|workbook|presentation|slides|pdf|document)\b.{0,80}\b(?:create|edit|modify|generate|build)\b", 1, "artifact_work"),
)


def _load() -> dict:
    if not ROUTING_FILE.exists():
        return {"mode": DEFAULT_MODE}
    try:
        value = json.loads(ROUTING_FILE.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return value
    except Exception:
        pass
    return {"mode": DEFAULT_MODE}


def _save(value: dict) -> None:
    ROUTING_FILE.parent.mkdir(parents=True, exist_ok=True)
    ROUTING_FILE.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def get_mode() -> str:
    configured = str(_load().get("mode") or DEFAULT_MODE).strip().lower()
    return configured if configured in VALID_MODES else DEFAULT_MODE


def set_mode(mode: str) -> dict:
    normalized = str(mode or "").strip().lower()
    if normalized not in VALID_MODES:
        raise ValueError("Model mode must be local, auto, or powerful.")
    state = _load()
    state["mode"] = normalized
    state["updated_at"] = time.time()
    _save(state)
    return routing_status(verify_local=False)


def local_model_name() -> str:
    return os.getenv("AGENTIE_LOCAL_MODEL", DEFAULT_LOCAL_MODEL).strip() or DEFAULT_LOCAL_MODEL


def local_base_url() -> str:
    return os.getenv("AGENTIE_LOCAL_BASE_URL", DEFAULT_LOCAL_BASE_URL).strip().rstrip("/") or DEFAULT_LOCAL_BASE_URL


def _local_enabled() -> bool:
    raw = os.getenv("AGENTIE_LOCAL_ENABLED", "auto").strip().lower()
    return raw not in {"0", "false", "off", "no", "disabled"}


def _probe_local_socket(timeout: float = 0.25) -> tuple[bool, str | None]:
    if not _local_enabled():
        return False, "Local model runtime is disabled."
    parsed = urlsplit(local_base_url())
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=max(0.05, min(timeout, 2.0))):
            return True, None
    except OSError as exc:
        return False, str(exc)[:240]


def local_runtime_status(*, verify: bool = True, cache_seconds: float = 4.0) -> dict:
    now = time.monotonic()
    if verify:
        with _STATUS_LOCK:
            cached = _STATUS_CACHE.get("value")
            at = float(_STATUS_CACHE.get("at") or 0.0)
            if isinstance(cached, dict) and now - at <= max(0.0, cache_seconds):
                return dict(cached)
    available = False
    error = None
    if verify:
        available, error = _probe_local_socket(float(os.getenv("AGENTIE_LOCAL_PROBE_TIMEOUT", "0.25")))
    result = {
        "enabled": _local_enabled(),
        "available": available if verify else None,
        "provider": "local",
        "model": local_model_name(),
        "base_url": local_base_url(),
        "error": error,
    }
    if verify:
        with _STATUS_LOCK:
            _STATUS_CACHE["at"] = now
            _STATUS_CACHE["value"] = dict(result)
    return result


def powerful_provider_name() -> str:
    configured = os.getenv("AGENTIE_PROVIDER", "").strip().lower()
    if configured in {"google", "google_ai", "google-ai", "gemini", "google_ai_studio"}:
        return "gemini"
    if configured in {"openrouter", "open_router"}:
        return "openrouter"
    if (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")) and not os.getenv("OPENROUTER_API_KEY"):
        return "gemini"
    return "openrouter"


def powerful_configured() -> bool:
    if powerful_provider_name() == "gemini":
        return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    return bool(os.getenv("OPENROUTER_API_KEY"))


def classify_task(message: str) -> dict:
    text = " ".join(str(message or "").split())
    lower = text.lower()
    score = 0
    reasons: list[str] = []
    for pattern, points, reason in _POWERFUL_PATTERNS:
        if re.search(pattern, lower, flags=re.IGNORECASE | re.DOTALL):
            score += points
            reasons.append(reason)
    if len(text) > 6500:
        score += 2
        reasons.append("large_context")
    elif len(text) > 2600:
        score += 1
        reasons.append("long_context")
    instruction_markers = len(re.findall(r"(?:^|[.;]\s+)(?:then|next|after|also|finally|and then)\b", lower))
    if instruction_markers >= 3:
        score += 1
        reasons.append("many_steps")
    return {"score": score, "requires_powerful": score >= 2, "reasons": list(dict.fromkeys(reasons))}


def choose_model_route(message: str, *, mode: str | None = None, local_available: bool | None = None, cloud_configured: bool | None = None) -> dict:
    selected_mode = (mode or get_mode()).strip().lower()
    if selected_mode not in VALID_MODES:
        selected_mode = DEFAULT_MODE
    task = classify_task(message)
    if local_available is None:
        local_available = bool(local_runtime_status(verify=True).get("available"))
    if cloud_configured is None:
        cloud_configured = powerful_configured()
    common = {"mode": selected_mode, "local_available": bool(local_available), "cloud_configured": bool(cloud_configured), "task": task}
    if selected_mode == "local":
        return {**common, "tier": "local", "reason": "manual_local", "allow_cloud_fallback": False}
    if selected_mode == "powerful":
        return {**common, "tier": "powerful", "reason": "manual_powerful", "allow_cloud_fallback": False}
    if not local_available:
        return {**common, "tier": "powerful", "reason": "local_runtime_unavailable", "allow_cloud_fallback": False}
    if task["requires_powerful"] and cloud_configured:
        return {**common, "tier": "powerful", "reason": task["reasons"][0] if task["reasons"] else "complex_task", "allow_cloud_fallback": False}
    return {
        **common,
        "tier": "local",
        "reason": "local_default" if not task["requires_powerful"] else "cloud_unavailable_best_effort_local",
        "allow_cloud_fallback": bool(cloud_configured),
    }


def should_escalate_local_error(exc: Exception) -> bool:
    text = str(exc or "").lower()
    blocked_signals = ("approval", "permission", "unauthorized tool", "user input required")
    if any(x in text for x in blocked_signals):
        return False
    if "model" in text and ("not found" in text or "unavailable" in text or "does not exist" in text):
        return True
    safe_signals = (
        "connection refused", "connection error", "connecterror", "failed to connect",
        "unsupported tool", "tools are not supported", "function calling",
        "context length", "context window", "timed out", "timeout",
    )
    return any(x in text for x in safe_signals)


def routing_status(*, verify_local: bool = True) -> dict:
    local = local_runtime_status(verify=verify_local)
    return {
        "mode": get_mode(),
        "modes": ["local", "auto", "powerful"],
        "local": local,
        "powerful": {"provider": powerful_provider_name(), "configured": powerful_configured()},
        "policy": {
            "auto_prefers_local": True,
            "local_never_falls_back_to_cloud": True,
            "powerful_always_uses_cloud": True,
        },
    }
