from __future__ import annotations

from typing import Any

from agentie.core.company_knowledge import (
    add_company_knowledge,
    delete_company_knowledge,
    list_company_knowledge,
    update_company_knowledge,
)
from agentie.core.file_service import (
    UPLOADS,
    checksum,
    ensure_dirs,
    extract_text,
    inspect_file,
    preview_data,
    resolve_upload,
    save_upload,
)
from agentie.mcp_runtime import make_server, require_approval

SERVER_ID = "agentie-workspace"
mcp = make_server("Agentie Workspace")


@mcp.tool()
def list_workspace_uploads(limit: int = 100) -> list[dict[str, Any]]:
    """List files in Agentie's confined workspace/uploads directory."""
    ensure_dirs()
    maximum = max(1, min(int(limit), 500))
    files = sorted((path for path in UPLOADS.iterdir() if path.is_file()), key=lambda path: path.stat().st_mtime, reverse=True)
    return [inspect_file(path) for path in files[:maximum]]


@mcp.tool()
def inspect_workspace_file(name: str) -> dict[str, Any]:
    """Inspect one uploaded workspace file without modifying it."""
    return inspect_file(resolve_upload(name))


@mcp.tool()
def read_workspace_file_text(name: str) -> dict[str, Any]:
    """Extract text from a supported uploaded file such as PDF, CSV, JSON, YAML, Markdown or source code."""
    return extract_text(resolve_upload(name))


@mcp.tool()
def preview_workspace_data(name: str) -> dict[str, Any]:
    """Preview CSV, JSON or YAML data from one uploaded workspace file."""
    return preview_data(resolve_upload(name))


@mcp.tool()
def checksum_workspace_file(name: str) -> dict[str, Any]:
    """Calculate SHA-256 for one uploaded workspace file."""
    return checksum(resolve_upload(name))


@mcp.tool()
def write_workspace_text_file(
    name: str,
    text: str,
    approval_id: str = "",
) -> dict[str, Any]:
    """Create a UTF-8 text file in Agentie's uploads directory after approval."""
    raw = str(text or "").encode("utf-8")
    if len(raw) > 1_000_000:
        raise ValueError("MCP text-file writes are limited to 1 MB.")
    payload = {"name": name, "bytes": len(raw), "sha256_hint": __import__("hashlib").sha256(raw).hexdigest()[:24]}
    pending = require_approval(
        SERVER_ID,
        "write_workspace_text_file",
        payload,
        f"Create or add a persistent workspace text file named {name!r}.",
        approval_id,
    )
    if pending:
        return pending
    return {"written": True, "file": save_upload(name, raw)}


@mcp.tool()
def search_company_knowledge(query: str = "", limit: int = 50) -> list[dict[str, Any]]:
    """Search Agentie's shared company knowledge by text or category."""
    items = list_company_knowledge(max(1, min(int(limit), 300)))
    needle = str(query or "").strip().casefold()
    if not needle:
        return items
    return [
        item
        for item in items
        if needle in str(item.get("value") or "").casefold()
        or any(needle in str(category).casefold() for category in (item.get("categories") or []))
    ]


@mcp.tool()
def add_company_knowledge_item(
    statement: str,
    project_id: str = "",
    approval_id: str = "",
) -> dict[str, Any]:
    """Add durable shared company knowledge after approval."""
    payload = {"statement": statement, "project_id": project_id}
    pending = require_approval(
        SERVER_ID,
        "add_company_knowledge_item",
        payload,
        "Add durable information to Agentie's shared company knowledge.",
        approval_id,
    )
    if pending:
        return pending
    item = add_company_knowledge(statement, source="mcp", project_id=project_id or None)
    return {"added": True, "knowledge": item}


@mcp.tool()
def update_company_knowledge_item(
    knowledge_id: str,
    value: str,
    approval_id: str = "",
) -> dict[str, Any]:
    """Update one durable company-knowledge item after approval."""
    payload = {"knowledge_id": knowledge_id, "value": value}
    pending = require_approval(
        SERVER_ID,
        "update_company_knowledge_item",
        payload,
        f"Update shared company knowledge item {knowledge_id!r}.",
        approval_id,
    )
    if pending:
        return pending
    return {"updated": True, "knowledge": update_company_knowledge(knowledge_id, value)}


@mcp.tool()
def delete_company_knowledge_item(
    knowledge_id: str,
    approval_id: str = "",
) -> dict[str, Any]:
    """Delete one durable company-knowledge item after approval."""
    payload = {"knowledge_id": knowledge_id}
    pending = require_approval(
        SERVER_ID,
        "delete_company_knowledge_item",
        payload,
        f"Delete shared company knowledge item {knowledge_id!r}.",
        approval_id,
    )
    if pending:
        return pending
    deleted = delete_company_knowledge(knowledge_id)
    if not deleted:
        raise ValueError("Company knowledge item was not found.")
    return {"deleted": True, "knowledge_id": knowledge_id}


if __name__ == "__main__":
    mcp.run(transport="stdio")
