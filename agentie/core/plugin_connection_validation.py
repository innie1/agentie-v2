from __future__ import annotations

import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from agentie.core.plugin_credentials import server_environment


def _whatsapp_validation() -> dict[str, Any]:
    env = server_environment("whatsapp")
    token = str(env.get("WHATSAPP_ACCESS_TOKEN") or "").strip()
    phone_id = str(env.get("WHATSAPP_PHONE_NUMBER_ID") or "").strip()
    version = str(env.get("WHATSAPP_GRAPH_VERSION") or "v23.0").strip()
    if not token or not phone_id:
        raise ValueError("WhatsApp access token and Phone Number ID are required.")
    if not re.fullmatch(r"v\d+(?:\.\d+)?", version):
        version = "v23.0"
    url = f"https://graph.facebook.com/{version}/{phone_id}?fields=id,display_phone_number,verified_name"
    request = Request(
        url,
        method="GET",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": "Agentie-WhatsApp/1.0"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8", errors="replace")
            value = json.loads(raw or "{}")
            if not isinstance(value, dict) or not value.get("id"):
                raise RuntimeError("Meta did not return the configured WhatsApp phone-number resource.")
            return {
                "provider": "Meta WhatsApp Cloud API",
                "phone_number_id": str(value.get("id") or ""),
                "display_phone_number": str(value.get("display_phone_number") or ""),
                "verified_name": str(value.get("verified_name") or ""),
            }
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")[:2500]
        try:
            parsed = json.loads(raw);detail = str(((parsed.get("error") or {}).get("message") or raw))
        except Exception:
            detail = raw or str(exc)
        raise RuntimeError(f"Meta rejected the WhatsApp credentials (HTTP {exc.code}): {detail[:700]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach Meta to validate WhatsApp: {exc.reason}") from exc


def validate_plugin_connection(server_name: str) -> dict[str, Any] | None:
    """Run provider-specific validation after the MCP transport itself connects."""
    server = str(server_name or "").strip().lower()
    if server == "whatsapp":
        return _whatsapp_validation()
    return None
