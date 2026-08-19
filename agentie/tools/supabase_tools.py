import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from agents import function_tool

from agentie.tools.approval_tools import approval_is_granted


def _config() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_KEY", "")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY are not configured.")
    return url, key


def _headers(key: str) -> dict[str, str]:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


@function_tool
def supabase_select(table: str, select: str = "*", limit: int = 20) -> str:
    """Read rows from a configured Supabase table through the REST API."""
    if not table.replace("_", "").isalnum():
        raise ValueError("Invalid table name.")
    base, key = _config()
    query = urlencode({"select": select[:500], "limit": max(1, min(limit, 100))})
    req = Request(f"{base}/rest/v1/{table}?{query}", headers=_headers(key))
    with urlopen(req, timeout=15) as response:
        return response.read(500_000).decode("utf-8", errors="replace")


@function_tool
def supabase_insert(table: str, record_json: str, approval_id: str) -> str:
    """Insert one JSON object into Supabase after an explicit approved request.

    The approval action must exactly match `supabase_insert:<table>`.
    """
    if not table.replace("_", "").isalnum():
        raise ValueError("Invalid table name.")
    action = f"supabase_insert:{table}"
    if not approval_is_granted(action):
        raise PermissionError(
            f"A matching approved request is required. Expected approval action: {action}"
        )
    record = json.loads(record_json)
    if not isinstance(record, dict):
        raise ValueError("record_json must contain one JSON object.")
    base, key = _config()
    headers = _headers(key)
    headers["Prefer"] = "return=representation"
    req = Request(
        f"{base}/rest/v1/{table}",
        data=json.dumps(record).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(req, timeout=15) as response:
        return response.read(500_000).decode("utf-8", errors="replace")
