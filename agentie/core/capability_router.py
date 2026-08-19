from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agentie.core.mcp_client import (
    _approval_response,
    _error_text,
    _filesystem_root,
    _infer_natural_tool,
    execute_tool,
    get_server,
    inspect_server,
    list_servers,
)
from agentie.core.skill_registry import skills_for_agent

_STOPWORDS = {
    "a", "an", "and", "are", "at", "be", "can", "do", "for", "from", "in", "into", "is",
    "it", "me", "my", "of", "on", "please", "the", "this", "to", "using", "want", "what",
    "with", "you", "your",
}

# Native Agentie behavior wins for these intents. The automatic external router only
# runs after normal local routing, but these guards provide another regression barrier.
_NATIVE_GUARDS = (
    r"\b(?:timer|stopwatch|alarm|remind|reminder)\b",
    r"\b(?:calculate|calculator|convert)\b",
    r"\brun\s+(?:this\s+)?python\b|\bpython\s*:",
    r"\b(?:what time is it|current time|local time)\b",
    r"\bremember\s+(?:that\s+)?(?:my|i)\b",
)


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9_+-]+", str(value or "").lower())
        if len(token) > 1 and token not in _STOPWORDS
    }


def _native_guarded(text: str) -> bool:
    lower = str(text or "").lower()
    return any(re.search(pattern, lower, re.I) for pattern in _NATIVE_GUARDS)


def _windows_path(text: str) -> str | None:
    match = re.search(r"([A-Za-z]:\\[^\n\r\"']+)", text)
    return match.group(1).strip().rstrip(" .?!") if match else None


def _unix_path(text: str) -> str | None:
    # Require a slash-prefixed path with at least one additional component so normal
    # prose such as "and/or" is not mistaken for a filesystem location.
    match = re.search(r"(?<!\w)(/[^\s\"']+/[^\s\"']*)", text)
    return match.group(1).strip().rstrip(" .?!") if match else None


def _url(text: str) -> str | None:
    match = re.search(r"https?://[^\s<>\"']+", text, re.I)
    return match.group(0).rstrip(".,;!?)") if match else None


def _explicit_path(text: str) -> str | None:
    return _windows_path(text) or _unix_path(text)


def _server_by_names(*names: str) -> dict[str, Any] | None:
    wanted = {x.lower() for x in names}
    for server in list_servers():
        if str(server.get("name") or "").lower() in wanted:
            return server
    return None


def _looks_filesystem(text: str) -> bool:
    low = text.lower()
    nouns = re.search(r"\b(?:file|files|folder|folders|directory|directories|workspace)\b", low)
    verbs = re.search(r"\b(?:look|show|list|read|open|inspect|find|search|create|make|write|edit|move|rename|tree|info|details)\b", low)
    place = _explicit_path(text) is not None or "workspace" in low or "this place" in low or "this folder" in low or "this directory" in low
    return bool(nouns and verbs and place)


def _looks_git(text: str) -> bool:
    low = text.lower()
    return bool(
        re.search(r"\b(?:git|repository|repo)\b", low)
        and re.search(r"\b(?:status|diff|commit|commits|branch|branches|log|history|show|list|inspect|search)\b", low)
    )


def _looks_fetch(text: str) -> bool:
    low = text.lower()
    return bool(_url(text) and re.search(r"\b(?:fetch|read|open|inspect|get|retrieve|page|website|url)\b", low))


def _looks_graph_memory(text: str) -> bool:
    low = text.lower()
    return bool(
        re.search(r"\b(?:knowledge graph|entity|entities|relation|relations|graph memory)\b", low)
        and re.search(r"\b(?:create|add|search|find|show|list|read|delete|remove)\b", low)
    )


def _tool_map(info: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("name") or "").lower(): item for item in info.get("tools") or [] if item.get("name")}


def _pick_name(info: dict[str, Any], names: tuple[str, ...]) -> str | None:
    tools = _tool_map(info)
    for name in names:
        if name.lower() in tools:
            return str(tools[name.lower()].get("name"))
    return None


def _schema_for(info: dict[str, Any], tool_name: str) -> dict[str, Any]:
    for item in info.get("tools") or []:
        if str(item.get("name") or "").lower() == tool_name.lower():
            value = item.get("input_schema")
            return value if isinstance(value, dict) else {}
    return {}


def _required(schema: dict[str, Any]) -> list[str]:
    value = schema.get("required")
    return [str(x) for x in value] if isinstance(value, list) else []


def _infer_common_arguments(text: str, schema: dict[str, Any], server: dict[str, Any]) -> dict[str, Any] | None:
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = _required(schema)
    args: dict[str, Any] = {}
    path = _explicit_path(text)
    root = _filesystem_root(server)
    url = _url(text)

    for key in props:
        lower = key.lower()
        if lower in {"path", "directory", "directory_path", "file", "file_path"}:
            if path or root:
                args[key] = path or root
        elif lower in {"url", "uri"} and url:
            args[key] = url
        elif lower in {"query", "pattern", "search", "search_term"}:
            quoted = re.search(r"[\"']([^\"']+)[\"']", text)
            if quoted:
                args[key] = quoted.group(1)

    if any(key not in args for key in required):
        return None
    return args


def _lexical_tool(text: str, info: dict[str, Any], server: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    query = _tokens(text)
    if not query:
        return None
    best: tuple[int, str, dict[str, Any]] | None = None
    for item in info.get("tools") or []:
        name = str(item.get("name") or "")
        hay = " ".join([name, str(item.get("title") or ""), str(item.get("description") or "")])
        tool_tokens = _tokens(hay.replace("_", " "))
        overlap = len(query & tool_tokens)
        if overlap < 2:
            continue
        schema = item.get("input_schema") if isinstance(item.get("input_schema"), dict) else {}
        args = _infer_common_arguments(text, schema, server)
        if args is None:
            continue
        score = overlap * 2 + (1 if str(server.get("name") or "").lower() in query else 0)
        if best is None or score > best[0]:
            best = (score, name, args)
    if best and best[0] >= 4:
        return best[1], best[2]
    return None


def _filesystem_choice(text: str, server: dict[str, Any], info: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    # Reuse the explicit-plugin inference first; it already understands the official
    # Filesystem server's common tools.
    direct = _infer_natural_tool(text, server, info)
    if direct:
        return direct

    low = text.lower()
    root = _filesystem_root(server)
    path = _explicit_path(text) or root
    if not path:
        return None
    if re.search(r"\b(?:look at|show|list|inspect)\b", low) and re.search(r"\b(?:files|folder|directory|workspace|place)\b", low):
        tool = _pick_name(info, ("list_directory", "list_directory_with_sizes"))
        if tool:
            return tool, {"path": path}
    return _lexical_tool(text, info, server)


def _git_choice(text: str, server: dict[str, Any], info: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    low = text.lower()
    mapping = [
        (("status",), ("git_status", "status")),
        (("diff", "changes"), ("git_diff_unstaged", "git_diff", "diff")),
        (("log", "history", "commits"), ("git_log", "log")),
        (("branches", "branch"), ("git_branch", "list_branches", "branches")),
    ]
    for words, names in mapping:
        if any(word in low for word in words):
            tool = _pick_name(info, names)
            if tool:
                schema = _schema_for(info, tool)
                args = _infer_common_arguments(text, schema, server)
                if args is not None:
                    # mcp-server-git commonly requires repo_path. The registration
                    # already pins a repository, but supply cwd when the schema asks.
                    for key in _required(schema):
                        if key.lower() in {"repo_path", "repository", "repository_path"} and key not in args:
                            args[key] = str(Path.cwd())
                    if all(key in args for key in _required(schema)):
                        return tool, args
    return _lexical_tool(text, info, server)


def _fetch_choice(text: str, server: dict[str, Any], info: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    url = _url(text)
    if not url:
        return None
    tool = _pick_name(info, ("fetch", "fetch_url", "get_url"))
    if not tool:
        return _lexical_tool(text, info, server)
    schema = _schema_for(info, tool)
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    key = "url" if "url" in props or not props else next((x for x in props if x.lower() in {"url", "uri"}), "url")
    args = {key: url}
    if all(name in args for name in _required(schema)):
        return tool, args
    return None


def _memory_choice(text: str, server: dict[str, Any], info: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    return _lexical_tool(text, info, server)


async def _prepare(server: dict[str, Any], text: str, chooser) -> dict[str, Any] | None:
    name = str(server.get("name") or "")
    if not name:
        return None
    try:
        info = await inspect_server(name)
    except Exception:
        return None
    choice = chooser(text, server, info)
    if not choice:
        return None
    tool_name, arguments = choice
    canonical = f"Call MCP {name} tool {tool_name} with {json.dumps(arguments, ensure_ascii=False)}"
    approval = _approval_response(name, tool_name, arguments, canonical, natural=True)
    if approval.get("approved"):
        try:
            return await execute_tool(name, tool_name, arguments)
        except Exception as exc:
            return {"message": f"The approved MCP tool call could not complete: {_error_text(exc)}", "card": None}
    return approval


async def route_capability_request(message: str, agent_type: str = "general") -> dict[str, Any] | None:
    """Route an unresolved request to an installed capability without requiring its name.

    This is intentionally conservative. Native Agentie skills are given first refusal by
    main.py; this layer is only for unresolved requests with strong external-capability
    signals. That keeps new integrations additive instead of replacing stable behavior.
    """
    text = " ".join(str(message or "").strip().split())
    if not text or _native_guarded(text):
        return None

    # Loading enabled skill manifests here makes capability routing aware of the same
    # skill registry used by the rest of Agentie. Future plugin/skill adapters can plug
    # into this module without changing the main router.
    _ = skills_for_agent(agent_type)

    if _looks_filesystem(text):
        server = _server_by_names("filesystem")
        if server:
            result = await _prepare(server, text, _filesystem_choice)
            if result:
                return result

    if _looks_git(text):
        server = _server_by_names("git")
        if server:
            result = await _prepare(server, text, _git_choice)
            if result:
                return result

    if _looks_fetch(text):
        server = _server_by_names("fetch")
        if server:
            result = await _prepare(server, text, _fetch_choice)
            if result:
                return result

    if _looks_graph_memory(text):
        server = _server_by_names("memory")
        if server:
            result = await _prepare(server, text, _memory_choice)
            if result:
                return result

    return None
