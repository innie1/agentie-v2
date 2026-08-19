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

_MEMORY_PATTERNS = (
    r"\bremember\b",
    r"\bwhat (?:is|was) my\b",
    r"\bwhat did i (?:just )?(?:ask|save|tell)\b",
    r"\bshow (?:my )?memories\b",
    r"\blist (?:my )?memories\b",
)

_ATTACHMENT_REASONING = re.compile(
    r"\b(?:summari[sz]e|summary|read|analy[sz]e|explain|review|contents?|key points?|overview|what does|what is in)\b",
    re.IGNORECASE,
)


def _install_compound_splitter_fix() -> None:
    """Repair compound clauses such as `convert X, and then explain ...`.

    local_router is already loaded by main.py before provider_gate. Keeping this
    compatibility shim here avoids changing historical parser behavior elsewhere
    while ensuring a trailing conjunction never becomes part of a utility clause.
    """
    try:
        from agentie.core import local_router

        def split_commands(text: str) -> list[str]:
            normalized = re.sub(r"\s+", " ", text.strip())
            # Consume "and then" as one separator so the previous command does
            # not end in a stray "and" that breaks anchored utility regexes.
            parts = re.split(r"\s*(?:;|\b(?:and\s+)?then\b)\s*", normalized, flags=re.IGNORECASE)
            expanded: list[str] = []
            command_start = (
                r"(?:calculate|calculator|convert|set|start|pause|stop|reset|remind|reminder|show|list|"
                r"what|tell|give|weather|wheather|forecast|temperature|wiki|wikipedia|look|rss|system|"
                r"countdown|sha256|checksum|image|inspect|scratchpad|note|save|cancel|time|clock)"
            )
            for part in parts:
                part = re.sub(r"(?:,?\s+and)\s*$", "", part.strip(), flags=re.IGNORECASE)
                chunks = re.split(
                    rf"\s*,\s*(?:and\s+)?(?={command_start}\b)|\s+and\s+(?={command_start}\b)",
                    part,
                    flags=re.IGNORECASE,
                )
                for chunk in chunks:
                    cleaned = re.sub(r"(?:,?\s+and)\s*$", "", chunk.strip(" .?!"), flags=re.IGNORECASE).strip(" .?!")
                    if cleaned:
                        expanded.append(cleaned)
            return expanded

        local_router._split_commands = split_commands
    except Exception:
        # Routing should still start even if an older installation lacks the
        # private splitter; the normal local router remains available.
        pass


_install_compound_splitter_fix()


def _attachment_reasoning_allowed(message: str) -> bool:
    text = message.lower()
    # The frontend only adds this phrase after a successful local upload. This
    # allows reasoning about an explicitly attached file while keeping generic
    # unresolved file commands behind the local-first gate.
    has_attachment_context = "attached file:" in text or "attached files:" in text or "attached workspace file" in text
    return has_attachment_context and bool(_ATTACHMENT_REASONING.search(text))


def looks_local_first(message: str) -> bool:
    text = message.lower().strip()
    if _attachment_reasoning_allowed(message):
        return False
    words = set(re.findall(r"[a-z0-9_]+", text))
    if words & _LOCAL_TERMS:
        return True
    return any(re.search(pattern, text) for pattern in _MEMORY_PATTERNS)


def provider_allowed(message: str) -> bool:
    """Return True only when an unresolved message is appropriate for an LLM.

    Explicit attachment reasoning is allowed because the file has already been
    uploaded locally and the model has file-reading tools. Other local/free-first
    intent remains conservative: parser misses should not become accidental paid
    requests.
    """
    if _attachment_reasoning_allowed(message):
        return True
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
