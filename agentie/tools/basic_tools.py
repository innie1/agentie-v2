from datetime import datetime, timezone

from agents import function_tool


@function_tool
def get_current_utc_time() -> str:
    """Return the current UTC date and time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()
