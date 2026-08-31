from __future__ import annotations

import os
from typing import Any

from agentie.core.telegram_channel import public_state as telegram_public_state
from agentie.core.telegram_channel import queue_proactive as queue_telegram_proactive
from agentie.core.whatsapp_cloud import get_message, list_messages, send_text_message
from agentie.mcp_runtime import make_server, require_approval

SERVER_ID = "agentie-channels"
mcp = make_server("Agentie Communications")


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
def get_channel_status(owner_id: str = "local-user") -> dict[str, Any]:
    """Get safe connection status for Agentie's real messaging channels."""
    telegram = telegram_public_state(owner_id)
    return {
        "telegram": telegram,
        "whatsapp": {
            "configured": bool(os.getenv("WHATSAPP_ACCESS_TOKEN") and os.getenv("WHATSAPP_PHONE_NUMBER_ID")),
            "provider": "Meta WhatsApp Cloud API",
        },
    }


@mcp.tool()
def list_channel_messages(
    channel: str = "whatsapp",
    limit: int = 20,
    recipient: str = "",
    direction: str = "",
    needs_human: bool | None = None,
) -> list[dict[str, Any]]:
    """List locally recorded messages for channels that keep a local message ledger.

    WhatsApp Cloud currently has a queryable message ledger. Telegram is a
    paired remote doorway and does not expose a generic local-history API, so
    callers should use normal Agentie chat/thread history for Telegram context.
    """
    selected = str(channel or "").strip().casefold()
    if selected != "whatsapp":
        raise ValueError("Queryable channel history is currently available for WhatsApp only.")
    return list_messages(
        limit=max(1, min(int(limit), 100)),
        phone=recipient or None,
        direction=direction or None,
        needs_human=needs_human,
    )


@mcp.tool()
def get_channel_message(channel: str, message_id: str) -> dict[str, Any]:
    """Get one locally recorded channel message."""
    selected = str(channel or "").strip().casefold()
    if selected != "whatsapp":
        raise ValueError("Individual message lookup is currently available for WhatsApp only.")
    item = get_message(message_id)
    if not item:
        raise ValueError("Channel message was not found.")
    return item


@mcp.tool()
def send_channel_message(
    channel: str,
    text: str,
    recipient: str = "",
    owner_id: str = "local-user",
    agent_id: str = "",
    agent_name: str = "",
    agent_role: str = "",
    company_identity: str = "",
    approval_id: str = "",
) -> dict[str, Any]:
    """Send a real message through Telegram or Meta WhatsApp Cloud after approval."""
    selected = str(channel or "").strip().casefold()
    if selected not in {"telegram", "whatsapp"}:
        raise ValueError("Supported communication channels are telegram and whatsapp.")
    if selected == "whatsapp" and not str(recipient or "").strip():
        raise ValueError("A WhatsApp recipient phone number is required.")
    payload = {
        "channel": selected,
        "recipient": recipient if selected == "whatsapp" else owner_id,
        "text": str(text or ""),
        "agent_id": agent_id,
    }
    pending = require_approval(
        SERVER_ID,
        "send_channel_message",
        payload,
        f"Send an external {selected.title()} message.",
        approval_id,
    )
    if pending:
        return pending
    if selected == "telegram":
        queued = queue_telegram_proactive(text, owner_id=owner_id or None)
        if queued < 1:
            raise RuntimeError("No paired Telegram account is available for this owner.")
        return {"sent": True, "channel": "telegram", "queued_recipients": queued}
    result = send_text_message(
        recipient,
        text,
        agent=_agent(agent_id, agent_name, agent_role, company_identity),
    )
    return {"sent": True, "channel": "whatsapp", "result": result}


if __name__ == "__main__":
    mcp.run(transport="stdio")
