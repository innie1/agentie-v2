from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from mcp import Client

WORKSPACE = Path.cwd() / "workspace"
REGISTRY = WORKSPACE / "mcp_servers.json"


def _load() -> dict[str, dict[str, Any]]:
    try:
        return json.loads(REGISTRY.read_text(encoding="utf-8")) if REGISTRY.exists() else {}
    except Exception:
        return {}


def _save(data: dict[str, dict[str, Any]]) -> None:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def _clean_name(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-")
    return name[:80]


def add_server(name: str, url: str) -> dict[str, Any]:
    key = _clean_name(name)
    if not key:
        raise ValueError("MCP server name is required.")
    if not _valid_url(url):
        raise ValueError("MCP server URL must start with http:// or https://.")
    data = _load()
    data[key] = {"name": key, "url": url.rstrip("/"), "transport": "streamable_http", "enabled": True}
    _save(data)
    return data[key]


def remove_server(name: str) -> bool:
    key = _clean_name(name)
    data = _load()
    if key not in data:
        return False
    del data[key]
    _save(data)
    return True


def list_servers() -> list[dict[str, Any]]:
    return sorted(_load().values(), key=lambda x: str(x.get("name", "")).lower())


def get_server(name: str) -> dict[str, Any] | None:
    return _load().get(_clean_name(name))


def _safe_model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except Exception:
            return value.model_dump()
    return value


async def inspect_server(name: str) -> dict[str, Any]:
    server = get_server(name)
    if not server:
        raise ValueError(f"MCP server '{name}' is not registered.")

    async with Client(server["url"]) as client:
        tool_result = await client.list_tools()
        resource_result = await client.list_resources()
        prompt_result = await client.list_prompts()
        template_result = await client.list_resource_templates()

        tools = []
        for tool in getattr(tool_result, "tools", []) or []:
            tools.append({
                "name": getattr(tool, "name", None),
                "title": getattr(tool, "title", None),
                "description": getattr(tool, "description", None),
                "input_schema": _safe_model_dump(getattr(tool, "input_schema", None)),
            })

        resources = []
        for resource in getattr(resource_result, "resources", []) or []:
            resources.append({
                "name": getattr(resource, "name", None),
                "title": getattr(resource, "title", None),
                "uri": str(getattr(resource, "uri", "")),
                "description": getattr(resource, "description", None),
            })

        prompts = []
        for prompt in getattr(prompt_result, "prompts", []) or []:
            prompts.append({
                "name": getattr(prompt, "name", None),
                "title": getattr(prompt, "title", None),
                "description": getattr(prompt, "description", None),
            })

        templates = []
        for item in getattr(template_result, "resource_templates", []) or []:
            templates.append({
                "name": getattr(item, "name", None),
                "title": getattr(item, "title", None),
                "uri_template": str(getattr(item, "uri_template", "")),
                "description": getattr(item, "description", None),
            })

        info = getattr(client, "server_info", None)
        return {
            "type": "mcp_server",
            "name": server["name"],
            "url": server["url"],
            "transport": server["transport"],
            "protocol_version": str(getattr(client, "protocol_version", "")),
            "server_info": {
                "name": getattr(info, "name", None) if info else None,
                "version": getattr(info, "version", None) if info else None,
            },
            "tools": tools,
            "resources": resources,
            "resource_templates": templates,
            "prompts": prompts,
            "execution_enabled": False,
        }


def _server_list_card(items: list[dict[str, Any]]) -> dict[str, Any]:
    lines = []
    for item in items:
        lines.append(f"{item['name']} — {item['url']}")
    return {"type": "note", "title": f"MCP servers · {len(items)}", "content": "\n".join(lines) if lines else "No MCP servers registered."}


def _inspect_card(info: dict[str, Any]) -> dict[str, Any]:
    lines = [
        f"URL: {info['url']}",
        f"Protocol: {info.get('protocol_version') or 'unknown'}",
        f"Tools: {len(info.get('tools') or [])}",
        f"Resources: {len(info.get('resources') or [])}",
        f"Resource templates: {len(info.get('resource_templates') or [])}",
        f"Prompts: {len(info.get('prompts') or [])}",
        "Tool execution: disabled until approval gating is enabled",
    ]
    if info.get("tools"):
        lines.append("\nTools")
        for tool in info["tools"][:30]:
            label = tool.get("title") or tool.get("name") or "tool"
            lines.append(f"- {label}")
    return {"type": "note", "title": f"MCP · {info['name']}", "content": "\n".join(lines)}


async def route_mcp_command(message: str) -> dict[str, Any] | None:
    text = " ".join(str(message or "").strip().split())
    low = text.lower().strip(" .?!")

    if low in {"mcp", "mcp servers", "list mcp servers", "show mcp servers", "show mcp"}:
        items = list_servers()
        return {"message": f"There are {len(items)} registered MCP server(s).", "card": _server_list_card(items)}

    add = re.match(r"^(?:add|register|connect)\s+(?:an?\s+)?mcp\s+server\s+([\w.-]+)\s+(https?://\S+)$", text, re.I)
    if add:
        try:
            item = add_server(add.group(1), add.group(2))
        except ValueError as exc:
            return {"message": str(exc), "card": None}
        return {"message": f"Registered MCP server '{item['name']}'.", "card": _server_list_card([item])}

    remove = re.match(r"^(?:remove|delete|disconnect)\s+(?:the\s+)?mcp\s+server\s+([\w.-]+)$", text, re.I)
    if remove:
        if not remove_server(remove.group(1)):
            return {"message": "That MCP server is not registered.", "card": None}
        return {"message": f"Removed MCP server '{_clean_name(remove.group(1))}'.", "card": _server_list_card(list_servers())}

    inspect = re.match(r"^(?:inspect|discover|test|check)\s+(?:the\s+)?mcp\s+(?:server\s+)?([\w.-]+)$", text, re.I)
    if inspect:
        try:
            info = await inspect_server(inspect.group(1))
        except Exception as exc:
            return {"message": f"Could not connect to that MCP server: {str(exc)[:220]}", "card": None}
        return {"message": f"Connected to MCP server '{info['name']}' and discovered its capabilities.", "card": _inspect_card(info)}

    return None
