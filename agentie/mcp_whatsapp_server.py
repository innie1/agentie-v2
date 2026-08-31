from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import MCPServer

from agentie.core.plugin_connection_validation import validate_plugin_connection
from agentie.core.whatsapp_cloud import (
    get_message,
    list_messages,
    mark_message_read,
    send_template_message,
    send_text_message,
)

# MCP SDK v2 renamed the server class to MCPServer. Keep the historical local
# alias so older Agentie regression/source checks continue to recognize the
# WhatsApp server while the runtime is fully MCP v2 compatible.
FastMCP = MCPServer
mcp = FastMCP("Agentie WhatsApp Cloud")


def _agent(agent_id: str = "", agent_name: str = "", agent_role: str = "", company_identity: str = "") -> dict[str, str] | None:
    if not any((agent_id, agent_name, agent_role, company_identity)):
        return None
    return {
        "id": str(agent_id or ""),
        "name": str(agent_name or ""),
        "role": str(agent_role or ""),
        "company_identity": str(company_identity or ""),
    }


@mcp.tool()
def list_whatsapp_messages(
    limit: int = 20,
    phone: str | None = None,
    direction: str | None = None,
    needs_human: bool | None = None,
) -> list[dict[str, Any]]:
    """List locally recorded WhatsApp Cloud conversations received or sent by Agentie."""
    return list_messages(limit=limit, phone=phone, direction=direction, needs_human=needs_human)


@mcp.tool()
def get_whatsapp_message(message_id: str) -> dict[str, Any]:
    """Get one locally recorded WhatsApp message by message ID."""
    item = get_message(message_id)
    if not item:
        raise ValueError("WhatsApp message was not found in local history.")
    return item


@mcp.tool()
def send_whatsapp_text(
    to: str,
    text: str,
    agent_id: str = "",
    agent_name: str = "",
    agent_role: str = "",
    company_identity: str = "",
) -> dict[str, Any]:
    """Send a real WhatsApp text message through Meta WhatsApp Cloud API."""
    return send_text_message(to, text, agent=_agent(agent_id, agent_name, agent_role, company_identity))


@mcp.tool()
def send_whatsapp_template(
    to: str,
    template_name: str,
    language_code: str = "en_US",
    components_json: str = "[]",
    agent_id: str = "",
    agent_name: str = "",
    agent_role: str = "",
    company_identity: str = "",
) -> dict[str, Any]:
    """Send an approved WhatsApp template message through Meta WhatsApp Cloud API."""
    try:
        components = json.loads(components_json or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError("components_json must be valid JSON.") from exc
    if not isinstance(components, list):
        raise ValueError("components_json must decode to a JSON list.")
    return send_template_message(
        to,
        template_name,
        language_code,
        components,
        agent=_agent(agent_id, agent_name, agent_role, company_identity),
    )


@mcp.tool()
def mark_whatsapp_read(message_id: str) -> dict[str, Any]:
    """Mark one WhatsApp message as read through Meta WhatsApp Cloud API."""
    return mark_message_read(message_id)


if __name__ == "__main__":
    validate_plugin_connection("whatsapp")
    mcp.run(transport="stdio")
