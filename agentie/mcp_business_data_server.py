from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from agentie.mcp_runtime import make_server, require_approval

SERVER_ID = "agentie-business-data"
mcp = make_server("Agentie Business Data")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


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


def _table(value: str) -> str:
    clean = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(clean):
        raise ValueError("Invalid Supabase table name.")
    return clean


def _filters(filters_json: str) -> dict[str, Any]:
    try:
        value = json.loads(filters_json or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("filters_json must be valid JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError("filters_json must decode to one JSON object.")
    if len(value) > 20:
        raise ValueError("At most 20 equality filters are allowed.")
    for key in value:
        if not _IDENTIFIER.fullmatch(str(key)):
            raise ValueError(f"Invalid filter column {key!r}.")
    return value


def _filter_pairs(filters: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for key, value in (filters or {}).items():
        if value is None:
            pairs.append((str(key), "is.null"))
        elif isinstance(value, bool):
            pairs.append((str(key), f"eq.{str(value).lower()}"))
        else:
            pairs.append((str(key), f"eq.{value}"))
    return pairs


def _query_string(select: str = "*", limit: int = 20, filters: dict[str, Any] | None = None) -> str:
    pairs: list[tuple[str, str]] = [
        ("select", str(select or "*")[:500]),
        ("limit", str(max(1, min(int(limit), 100)))),
        *_filter_pairs(filters),
    ]
    return urlencode(pairs)


def _mutation_query(filters: dict[str, Any]) -> str:
    return urlencode(_filter_pairs(filters))


def _decode_json(raw: bytes) -> Any:
    text = raw[:1_000_000].decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


@mcp.tool()
def get_business_data_status() -> dict[str, Any]:
    """Report which real business-data adapter is configured without exposing secrets."""
    configured = bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY"))
    return {
        "provider": "supabase",
        "configured": configured,
        "capabilities": ["select", "insert", "update", "delete"] if configured else [],
        "storeflow_adapter": False,
        "storeflow_note": "No StoreFlow-specific adapter exists in this Agentie repository yet; use the configured Supabase data source when it is the same backend.",
    }


@mcp.tool()
def query_business_table(
    table: str,
    select: str = "*",
    limit: int = 20,
    filters_json: str = "{}",
) -> Any:
    """Read rows from a configured Supabase table with optional equality filters."""
    clean_table = _table(table)
    filters = _filters(filters_json)
    base, key = _config()
    query = _query_string(select, limit, filters)
    request = Request(f"{base}/rest/v1/{clean_table}?{query}", headers=_headers(key))
    with urlopen(request, timeout=20) as response:
        return _decode_json(response.read(1_000_001))


@mcp.tool()
def insert_business_record(
    table: str,
    record_json: str,
    approval_id: str = "",
) -> dict[str, Any]:
    """Insert one Supabase row after an exact Agentie approval."""
    clean_table = _table(table)
    try:
        record = json.loads(record_json)
    except json.JSONDecodeError as exc:
        raise ValueError("record_json must be valid JSON.") from exc
    if not isinstance(record, dict):
        raise ValueError("record_json must contain one JSON object.")
    payload = {"table": clean_table, "record": record}
    pending = require_approval(
        SERVER_ID,
        "insert_business_record",
        payload,
        f"Insert a new row into Supabase table {clean_table!r}.",
        approval_id,
    )
    if pending:
        return pending
    base, key = _config()
    headers = _headers(key)
    headers["Prefer"] = "return=representation"
    request = Request(
        f"{base}/rest/v1/{clean_table}",
        data=json.dumps(record).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        return {"inserted": True, "rows": _decode_json(response.read(1_000_001))}


@mcp.tool()
def update_business_rows(
    table: str,
    changes_json: str,
    filters_json: str,
    approval_id: str = "",
) -> dict[str, Any]:
    """Update filtered Supabase rows after approval; mass updates are rejected."""
    clean_table = _table(table)
    try:
        changes = json.loads(changes_json)
    except json.JSONDecodeError as exc:
        raise ValueError("changes_json must be valid JSON.") from exc
    if not isinstance(changes, dict) or not changes:
        raise ValueError("changes_json must contain a non-empty JSON object.")
    filters = _filters(filters_json)
    if not filters:
        raise ValueError("At least one equality filter is required for an update.")
    payload = {"table": clean_table, "changes": changes, "filters": filters}
    pending = require_approval(
        SERVER_ID,
        "update_business_rows",
        payload,
        f"Update filtered rows in Supabase table {clean_table!r}.",
        approval_id,
    )
    if pending:
        return pending
    base, key = _config()
    headers = _headers(key)
    headers["Prefer"] = "return=representation"
    query = _mutation_query(filters)
    request = Request(
        f"{base}/rest/v1/{clean_table}?{query}",
        data=json.dumps(changes).encode("utf-8"),
        headers=headers,
        method="PATCH",
    )
    with urlopen(request, timeout=20) as response:
        return {"updated": True, "rows": _decode_json(response.read(1_000_001))}


@mcp.tool()
def delete_business_rows(
    table: str,
    filters_json: str,
    approval_id: str = "",
) -> dict[str, Any]:
    """Delete filtered Supabase rows after approval; mass deletes are rejected."""
    clean_table = _table(table)
    filters = _filters(filters_json)
    if not filters:
        raise ValueError("At least one equality filter is required for a delete.")
    payload = {"table": clean_table, "filters": filters}
    pending = require_approval(
        SERVER_ID,
        "delete_business_rows",
        payload,
        f"Delete filtered rows from Supabase table {clean_table!r}.",
        approval_id,
    )
    if pending:
        return pending
    base, key = _config()
    headers = _headers(key)
    headers["Prefer"] = "return=representation"
    query = _mutation_query(filters)
    request = Request(
        f"{base}/rest/v1/{clean_table}?{query}",
        headers=headers,
        method="DELETE",
    )
    with urlopen(request, timeout=20) as response:
        return {"deleted": True, "rows": _decode_json(response.read(1_000_001))}


if __name__ == "__main__":
    mcp.run(transport="stdio")
