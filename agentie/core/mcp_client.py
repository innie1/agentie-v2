from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from mcp import Client, ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agentie.tools.approval_tools import approval_is_granted, create_approval

WORKSPACE = Path.cwd() / "workspace"
REGISTRY = WORKSPACE / "mcp_servers.json"
_ALLOWED_LOCAL_COMMANDS = {
    "python", "python.exe", "py", "py.exe", "node", "node.exe", "npx", "npx.cmd",
    "uv", "uv.exe", "uvx", "uvx.exe", "pipx", "pipx.exe", "cmd", "cmd.exe",
}


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


def _split_local_command(command_line: str) -> tuple[str, list[str]]:
    value = str(command_line or "").strip()
    if not value:
        raise ValueError("A local MCP command is required.")
    try:
        parts = shlex.split(value, posix=os.name != "nt")
    except ValueError as exc:
        raise ValueError(f"Could not parse the local MCP command: {exc}") from exc
    if not parts:
        raise ValueError("A local MCP command is required.")

    command = parts[0].strip('"')
    base = Path(command).name.lower()
    if base not in _ALLOWED_LOCAL_COMMANDS:
        allowed = ", ".join(sorted({Path(x).stem for x in _ALLOWED_LOCAL_COMMANDS if not x.startswith("cmd")}))
        raise ValueError(f"Local MCP executables are limited to: {allowed}, plus the Windows cmd /c npx wrapper.")

    args = [part.strip('"') for part in parts[1:]]
    if base in {"cmd", "cmd.exe"}:
        wrapped = Path(args[1]).name.lower() if len(args) >= 2 else ""
        if len(args) < 3 or args[0].lower() != "/c" or wrapped not in {"npx", "npx.cmd"}:
            raise ValueError("For safety, cmd is only allowed as: cmd /c npx ... for an MCP server.")
    return command, args


def add_http_server(name: str, url: str) -> dict[str, Any]:
    key = _clean_name(name)
    if not key:
        raise ValueError("MCP server name is required.")
    if not _valid_url(url):
        raise ValueError("MCP server URL must start with http:// or https://.")
    data = _load()
    data[key] = {"name": key, "url": url.rstrip("/"), "transport": "streamable_http", "enabled": True}
    _save(data)
    return data[key]


def add_local_server(name: str, command_line: str) -> dict[str, Any]:
    key = _clean_name(name)
    if not key:
        raise ValueError("MCP server name is required.")
    command, args = _split_local_command(command_line)
    data = _load()
    data[key] = {"name": key, "transport": "stdio", "command": command, "args": args, "enabled": True}
    _save(data)
    return data[key]


def add_server(name: str, url: str) -> dict[str, Any]:
    return add_http_server(name, url)


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


def public_server(item: dict[str, Any]) -> dict[str, Any]:
    transport = str(item.get("transport") or "streamable_http")
    result = {"name": item.get("name"), "transport": transport, "enabled": bool(item.get("enabled", True))}
    if transport == "stdio":
        result["command"] = item.get("command")
        result["args"] = list(item.get("args") or [])
        result["display"] = " ".join([str(item.get("command") or "")] + [str(x) for x in item.get("args") or []]).strip()
    else:
        result["url"] = item.get("url")
        result["display"] = item.get("url")
    return result


def plugin_state() -> dict[str, Any]:
    servers = [public_server(x) for x in list_servers()]
    return {"plugins": [], "mcp_servers": servers, "mcp_count": len(servers), "execution_enabled": True}


def _safe_model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except Exception:
            return value.model_dump()
    return value


def _error_text(exc: BaseException) -> str:
    children = getattr(exc, "exceptions", None)
    if children:
        parts: list[str] = []
        for child in children:
            text = _error_text(child)
            if text and text not in parts:
                parts.append(text)
        if parts:
            return " | ".join(parts)[:700]
    text = str(exc).strip()
    if text and "unhandled errors in a TaskGroup" not in text:
        return text[:700]
    return exc.__class__.__name__


def _init_protocol(init: Any) -> str:
    return str(getattr(init, "protocolVersion", None) or getattr(init, "protocol_version", None) or "")


def _init_server_info(init: Any) -> tuple[str | None, str | None]:
    info = getattr(init, "serverInfo", None) or getattr(init, "server_info", None)
    if not info:
        return None, None
    return getattr(info, "name", None), getattr(info, "version", None)


def _normalize_discovery(server: dict[str, Any], client: Any, init: Any = None) -> dict[str, Any]:
    return {
        "type": "mcp_server",
        "name": server["name"],
        "transport": server.get("transport", "streamable_http"),
        "display": public_server(server).get("display"),
        "protocol_version": _init_protocol(init) if init is not None else str(getattr(client, "protocol_version", "")),
        "server_info": {},
        "tools": [],
        "resources": [],
        "resource_templates": [],
        "prompts": [],
        "execution_enabled": True,
    }


async def _discover_with_client(server: dict[str, Any], client: Any, init: Any = None) -> dict[str, Any]:
    info = _normalize_discovery(server, client, init)
    tool_result = await client.list_tools()
    info["tools"] = [
        {
            "name": getattr(t, "name", None),
            "title": getattr(t, "title", None),
            "description": getattr(t, "description", None),
            "input_schema": _safe_model_dump(getattr(t, "inputSchema", None) or getattr(t, "input_schema", None)),
        }
        for t in (getattr(tool_result, "tools", []) or [])
    ]
    try:
        resource_result = await client.list_resources()
        info["resources"] = [{"name": getattr(r, "name", None), "title": getattr(r, "title", None), "uri": str(getattr(r, "uri", "")), "description": getattr(r, "description", None)} for r in (getattr(resource_result, "resources", []) or [])]
    except Exception:
        info["resources"] = []
    try:
        prompt_result = await client.list_prompts()
        info["prompts"] = [{"name": getattr(p, "name", None), "title": getattr(p, "title", None), "description": getattr(p, "description", None)} for p in (getattr(prompt_result, "prompts", []) or [])]
    except Exception:
        info["prompts"] = []
    try:
        template_result = await client.list_resource_templates()
        info["resource_templates"] = [{"name": getattr(i, "name", None), "title": getattr(i, "title", None), "uri_template": str(getattr(i, "uriTemplate", None) or getattr(i, "uri_template", "")), "description": getattr(i, "description", None)} for i in (getattr(template_result, "resourceTemplates", None) or getattr(template_result, "resource_templates", []) or [])]
    except Exception:
        info["resource_templates"] = []
    if init is not None:
        server_name, version = _init_server_info(init)
        info["server_info"] = {"name": server_name, "version": version}
    else:
        server_info = getattr(client, "server_info", None)
        info["server_info"] = {"name": getattr(server_info, "name", None) if server_info else None, "version": getattr(server_info, "version", None) if server_info else None}
    return info


async def inspect_server(name: str) -> dict[str, Any]:
    server = get_server(name)
    if not server:
        raise ValueError(f"MCP server '{name}' is not registered.")
    if server.get("transport") == "stdio":
        params = StdioServerParameters(command=str(server.get("command") or ""), args=[str(x) for x in server.get("args") or []])
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    return await _discover_with_client(server, session, init)
        except Exception as exc:
            raise RuntimeError(_error_text(exc)) from exc
    try:
        async with Client(str(server.get("url") or "")) as client:
            return await _discover_with_client(server, client)
    except Exception as exc:
        raise RuntimeError(_error_text(exc)) from exc


def _approval_action(server_name: str, tool_name: str, arguments: dict[str, Any]) -> str:
    payload = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"mcp:{_clean_name(server_name)}:{tool_name}:{payload}"


def _content_text(block: Any) -> str:
    text = getattr(block, "text", None)
    if text is not None:
        return str(text)
    data = _safe_model_dump(block)
    try:
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception:
        return str(data)


def _tool_result(server_name: str, tool_name: str, result: Any) -> dict[str, Any]:
    blocks = getattr(result, "content", []) or []
    text = "\n\n".join(_content_text(block) for block in blocks).strip()
    if not text:
        dumped = _safe_model_dump(result)
        text = json.dumps(dumped, ensure_ascii=False, indent=2) if isinstance(dumped, (dict, list)) else str(dumped)
    text = text[:12000]
    is_error = bool(getattr(result, "isError", False) or getattr(result, "is_error", False))
    return {"message": f"MCP tool '{tool_name}' {'returned an error' if is_error else 'completed'} on '{_clean_name(server_name)}'.", "card": {"type": "note", "title": f"MCP · {_clean_name(server_name)} / {tool_name}", "content": text or "Tool completed without text output."}}


async def execute_tool(server_name: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    server = get_server(server_name)
    if not server:
        raise ValueError(f"MCP server '{server_name}' is not registered.")
    if server.get("transport") == "stdio":
        params = StdioServerParameters(command=str(server.get("command") or ""), args=[str(x) for x in server.get("args") or []])
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments)
                    return _tool_result(server_name, tool_name, result)
        except Exception as exc:
            raise RuntimeError(_error_text(exc)) from exc
    try:
        async with Client(str(server.get("url") or "")) as client:
            result = await client.call_tool(tool_name, arguments)
            return _tool_result(server_name, tool_name, result)
    except Exception as exc:
        raise RuntimeError(_error_text(exc)) from exc


def _server_list_card(items: list[dict[str, Any]]) -> dict[str, Any]:
    lines = []
    for item in items:
        public = public_server(item)
        label = "Local" if public["transport"] == "stdio" else "HTTP"
        lines.append(f"{public['name']} · {label} — {public.get('display') or ''}")
    return {"type": "note", "title": f"MCP servers · {len(items)}", "content": "\n".join(lines) if lines else "No MCP servers registered."}


def _inspect_card(info: dict[str, Any]) -> dict[str, Any]:
    transport = "Local stdio" if info.get("transport") == "stdio" else "Streamable HTTP"
    lines = [f"Transport: {transport}", f"Connection: {info.get('display') or ''}", f"Protocol: {info.get('protocol_version') or 'unknown'}", f"Tools: {len(info.get('tools') or [])}", f"Resources: {len(info.get('resources') or [])}", f"Resource templates: {len(info.get('resource_templates') or [])}", f"Prompts: {len(info.get('prompts') or [])}", "Tool execution: approval required"]
    if info.get("tools"):
        lines.append("\nTools")
        for tool in info["tools"][:30]:
            lines.append(f"- {tool.get('title') or tool.get('name') or 'tool'}")
    return {"type": "note", "title": f"MCP · {info['name']}", "content": "\n".join(lines)}


def _filesystem_root(server: dict[str, Any]) -> str | None:
    args = [str(x) for x in server.get("args") or []]
    package_names = {"@modelcontextprotocol/server-filesystem", "@modelcontextprotocol/server-filesystem@latest"}
    for index, arg in enumerate(args):
        if arg.lower() in package_names and index + 1 < len(args):
            return args[index + 1]
    return None


def _mentioned_server(text: str) -> str | None:
    low = text.lower()
    for server in list_servers():
        name = str(server.get("name") or "")
        if not name:
            continue
        patterns = (
            f"using the {name.lower()} plugin", f"using {name.lower()} plugin",
            f"with the {name.lower()} plugin", f"with {name.lower()} plugin",
            f"using the {name.lower()} mcp", f"using {name.lower()} mcp",
            f"with the {name.lower()} mcp", f"with {name.lower()} mcp",
            f"using {name.lower()}", f"with {name.lower()}",
        )
        if any(pattern in low for pattern in patterns):
            return name
    return None


def _extract_windows_path(text: str) -> str | None:
    match = re.search(r"([A-Za-z]:\\[^\n\r\"']+)", text)
    if match:
        value = match.group(1).strip().rstrip(" .?!")
        for marker in (" using ", " with "):
            pos = value.lower().find(marker)
            if pos > 0:
                value = value[:pos].rstrip()
        return value
    return None


def _basename_request(text: str, markers: tuple[str, ...]) -> str | None:
    low = text.lower()
    for marker in markers:
        pos = low.find(marker)
        if pos >= 0:
            tail = text[pos + len(marker):].strip(" :\"'`.")
            tail = re.split(r"\s+(?:using|with)\s+(?:the\s+)?[\w.-]+(?:\s+(?:plugin|mcp))?\b", tail, maxsplit=1, flags=re.I)[0].strip()
            if tail:
                return tail
    return None


def _pick_existing_tool(info: dict[str, Any], candidates: tuple[str, ...]) -> str | None:
    by_name = {str(tool.get("name") or "").lower(): str(tool.get("name") or "") for tool in info.get("tools") or []}
    for candidate in candidates:
        if candidate.lower() in by_name:
            return by_name[candidate.lower()]
    return None


def _infer_natural_tool(text: str, server: dict[str, Any], info: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    low = text.lower()
    root = _filesystem_root(server)

    if any(phrase in low for phrase in ("allowed directories", "allowed folders", "where can", "what directories can")):
        tool = _pick_existing_tool(info, ("list_allowed_directories",))
        if tool:
            return tool, {}

    if any(phrase in low for phrase in ("directory tree", "folder tree", "show the tree", "show tree")):
        tool = _pick_existing_tool(info, ("directory_tree",))
        if tool and root:
            return tool, {"path": _extract_windows_path(text) or root}

    if any(word in low for word in ("search files", "find files", "find file", "search for")):
        tool = _pick_existing_tool(info, ("search_files",))
        query = _basename_request(text, ("search for", "find files", "find file", "search files"))
        if tool and root and query:
            return tool, {"path": _extract_windows_path(text) or root, "pattern": query}

    if any(phrase in low for phrase in ("file info", "file details", "information about", "details about")):
        tool = _pick_existing_tool(info, ("get_file_info",))
        path = _extract_windows_path(text) or _basename_request(text, ("file info", "file details", "information about", "details about"))
        if tool and path:
            if root and not re.match(r"^[A-Za-z]:\\", path):
                path = str(Path(root) / path)
            return tool, {"path": path}

    if any(phrase in low for phrase in ("read file", "read the file", "open file", "open the file", "show file", "show the file")):
        tool = _pick_existing_tool(info, ("read_text_file", "read_file"))
        path = _extract_windows_path(text) or _basename_request(text, ("read the file", "read file", "open the file", "open file", "show the file", "show file"))
        if tool and path:
            if root and not re.match(r"^[A-Za-z]:\\", path):
                path = str(Path(root) / path)
            return tool, {"path": path}

    if any(phrase in low for phrase in ("show me the files", "show the files", "list the files", "list files", "files in my workspace", "files in the workspace", "what files")):
        tool = _pick_existing_tool(info, ("list_directory", "list_directory_with_sizes"))
        if tool and root:
            return tool, {"path": _extract_windows_path(text) or root}

    return None


def _approval_response(server_name: str, tool_name: str, arguments: dict[str, Any], command: str, natural: bool = False) -> dict[str, Any]:
    action = _approval_action(server_name, tool_name, arguments)
    if approval_is_granted(action):
        return {"approved": True, "action": action}
    approval = create_approval(action, f"Allow MCP server '{_clean_name(server_name)}' to run tool '{tool_name}' with the shown arguments.")
    return {
        "message": "I matched that request to an MCP tool. Approve it to continue." if natural else "This MCP tool call needs your approval before it can run.",
        "card": {"type": "mcp_approval", "approval": approval, "server": _clean_name(server_name), "tool": tool_name, "arguments": arguments, "command": command},
    }


async def _route_natural_mcp(text: str) -> dict[str, Any] | None:
    server_name = _mentioned_server(text)
    if not server_name:
        return None
    server = get_server(server_name)
    if not server:
        return None
    try:
        info = await inspect_server(server_name)
    except Exception as exc:
        return {"message": f"I found the '{server_name}' plugin, but could not connect to it: {_error_text(exc)}", "card": None}
    inferred = _infer_natural_tool(text, server, info)
    if not inferred:
        tools = [str(t.get("title") or t.get("name") or "") for t in info.get("tools") or []]
        preview = ", ".join(x for x in tools[:6] if x)
        return {"message": f"I found the '{server_name}' plugin, but I couldn't confidently choose a tool for that request. Available tools include: {preview}.", "card": None}
    tool_name, arguments = inferred
    canonical = f"Call MCP {server_name} tool {tool_name} with {json.dumps(arguments, ensure_ascii=False)}"
    approval = _approval_response(server_name, tool_name, arguments, canonical, natural=True)
    if approval.get("approved"):
        try:
            return await execute_tool(server_name, tool_name, arguments)
        except Exception as exc:
            return {"message": f"The approved MCP tool call could not complete: {_error_text(exc)}", "card": None}
    return approval


async def route_mcp_command(message: str) -> dict[str, Any] | None:
    text = " ".join(str(message or "").strip().split())
    low = text.lower().strip(" .?!")

    if low in {"mcp", "mcp servers", "list mcp servers", "show mcp servers", "show mcp"}:
        items = list_servers()
        return {"message": f"There are {len(items)} registered MCP server(s).", "card": _server_list_card(items)}

    add_http = re.match(r"^(?:add|register|connect)\s+(?:an?\s+)?mcp\s+server\s+([\w.-]+)\s+(https?://\S+)$", text, re.I)
    if add_http:
        try:
            item = add_http_server(add_http.group(1), add_http.group(2))
        except ValueError as exc:
            return {"message": str(exc), "card": None}
        return {"message": f"Registered HTTP MCP server '{item['name']}'.", "card": _server_list_card([item])}

    add_local = re.match(r"^(?:add|register|connect)\s+(?:an?\s+)?mcp\s+server\s+([\w.-]+)\s+(?:using|with)\s+(.+)$", text, re.I)
    if add_local:
        try:
            item = add_local_server(add_local.group(1), add_local.group(2))
        except ValueError as exc:
            return {"message": str(exc), "card": None}
        return {"message": f"Registered local MCP server '{item['name']}'. It will only start when you inspect or use it.", "card": _server_list_card([item])}

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
            return {"message": f"Could not connect to that MCP server: {_error_text(exc)}", "card": None}
        return {"message": f"Connected to MCP server '{info['name']}' and discovered its capabilities.", "card": _inspect_card(info)}

    call = re.match(r"^(?:call|use|run)\s+mcp\s+([\w.-]+)\s+(?:tool\s+)?([\w.-]+)(?:\s+with\s+(.+))?$", text, re.I)
    if call:
        server_name, tool_name = call.group(1), call.group(2)
        raw_args = (call.group(3) or "{}").strip()
        try:
            arguments = json.loads(raw_args)
            if not isinstance(arguments, dict):
                raise ValueError
        except Exception:
            return {"message": "MCP tool arguments must be a JSON object, for example: with {\"query\":\"hello\"}.", "card": None}
        if not get_server(server_name):
            return {"message": f"MCP server '{server_name}' is not registered.", "card": None}
        approval = _approval_response(server_name, tool_name, arguments, text)
        if approval.get("approved"):
            try:
                return await execute_tool(server_name, tool_name, arguments)
            except Exception as exc:
                return {"message": f"The approved MCP tool call could not complete: {_error_text(exc)}", "card": None}
        return approval

    natural = await _route_natural_mcp(text)
    if natural is not None:
        return natural

    return None
