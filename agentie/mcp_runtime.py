from __future__ import annotations

import hashlib
import json
from typing import Any

from mcp.server.mcpserver import MCPServer

from agentie.tools.approval_tools import approval_is_granted, create_approval


def make_server(name: str) -> MCPServer:
    """Create an Agentie-local MCP v2 server."""
    return MCPServer(name)


def _canonical_payload(payload: dict[str, Any] | None) -> str:
    return json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def approval_action(server: str, tool: str, payload: dict[str, Any] | None = None) -> str:
    """Return a short, stable action key for one exact consequential MCP call."""
    digest = hashlib.sha256(_canonical_payload(payload).encode("utf-8")).hexdigest()[:24]
    return f"mcp:{server}:{tool}:{digest}"


def require_approval(
    server: str,
    tool: str,
    payload: dict[str, Any] | None,
    reason: str,
    approval_id: str = "",
) -> dict[str, Any] | None:
    """Return an approval response when an action has not yet been approved.

    Agentie's normal MCP client also gates mutating external MCP tools. Internal
    MCP servers repeat that check at the server boundary so they remain safe if
    another MCP host launches them directly.
    """
    action = approval_action(server, tool, payload)
    if approval_is_granted(action, approval_id or None):
        return None
    item = create_approval(
        action,
        reason,
        {
            "kind": "mcp",
            "server": server,
            "tool": tool,
            "payload_fingerprint": action.rsplit(":", 1)[-1],
        },
    )
    return {
        "approval_required": True,
        "approval": item,
        "message": "This action needs approval before it can run.",
    }
