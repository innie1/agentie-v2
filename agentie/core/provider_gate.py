import re

# Intents that Agentie owns locally/free-first. If one of these is present,
# parser failure must NOT silently become a paid provider call.
_LOCAL_TERMS = {
    "time", "clock", "timer", "alarm", "stopwatch", "weather", "forecast", "temperature",
    "calculate", "calculator", "calc", "convert", "conversion", "remind", "reminder",
    "schedule", "task", "tasks", "note", "notes", "scratchpad", "clipboard", "file", "files",
    "zip", "unzip", "extract", "pdf", "checksum", "sha256", "hash", "json", "yaml", "csv",
    "system", "cpu", "ram", "memory", "disk", "status", "wikipedia", "wiki", "rss",
    "upload", "image", "metadata", "approval", "approvals", "countdown",
}

# Phrases that signal persistent/local memory operations rather than a request
# for broad model reasoning.
_MEMORY_PATTERNS = (
    r"\bremember\b",
    r"\bwhat (?:is|was) my\b",
    r"\bwhat did i (?:just )?(?:ask|save|tell)\b",
    r"\bshow (?:my )?memories\b",
    r"\blist (?:my )?memories\b",
)


def looks_local_first(message: str) -> bool:
    text = message.lower().strip()
    words = set(re.findall(r"[a-z0-9_]+", text))
    if words & _LOCAL_TERMS:
        return True
    return any(re.search(pattern, text) for pattern in _MEMORY_PATTERNS)


def provider_allowed(message: str) -> bool:
    """Return True only when an unresolved message is appropriate for an LLM.

    Local/free-first intent always wins. This is intentionally conservative:
    a missed utility parser should produce a clarification, never an accidental
    paid request.
    """
    return not looks_local_first(message)


def local_fallback_message(message: str) -> str:
    text = message.lower()
    if "timer" in text:
        return "I understood this as a timer request, but I’m missing or couldn’t parse the duration. Try something like 20 seconds."
    if "alarm" in text:
        return "I understood this as an alarm request, but I couldn’t parse the time. Try something like 07:30."
    if any(word in text for word in ("weather", "forecast", "temperature")):
        return "I understood this as a weather request, but I need a location."
    if any(word in text for word in ("calculate", "calculator", "calc")):
        return "I understood this as a calculation request, but I couldn’t parse the expression."
    if "convert" in text:
        return "I understood this as a conversion request, but I need a value, source unit, and target unit."
    if any(word in text for word in ("remind", "reminder")):
        return "I understood this as a reminder request, but I need the reminder details or time."
    if "pdf" in text:
        return "I understood this as a PDF request, but I couldn’t resolve what content should go into the PDF."
    if any(word in text for word in ("file", "zip", "upload", "checksum", "sha256")):
        return "I understood this as a local file request, but I couldn’t resolve the file or action."
    if re.search(r"\bremember\b|\bmy\b.*\b(?:codename|preference|name|memory)\b", text):
        return "I understood this as a memory request, but I couldn’t resolve the memory operation locally yet."
    return "I recognized this as a local Agentie utility request, but I couldn’t parse it confidently. Please rephrase it and I won’t send it to the paid model."
