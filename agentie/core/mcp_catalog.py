from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _npx(*args: str) -> str:
    command = " ".join(["npx", *args])
    return f"cmd /c {command}" if os.name == "nt" else command


def _repo_path() -> str:
    return str(Path.cwd())


def _workspace_path() -> str:
    return str((Path.cwd() / "workspace").resolve())


def _python() -> str:
    return "py" if os.name == "nt" else "python"


def presets() -> list[dict[str, Any]]:
    """Curated MCP presets. Presets are registration templates, not auto-installed code."""
    return [
        {
            "id": "filesystem",
            "name": "Filesystem",
            "description": "Official MCP filesystem server scoped to Agentie's workspace.",
            "transport": "stdio",
            "command": _npx("-y", "@modelcontextprotocol/server-filesystem", f'"{_workspace_path()}"'),
            "requires": "Node.js / npx",
            "capabilities": ["files", "folders", "search", "read", "write"],
            "auto_route": True,
        },
        {
            "id": "playwright",
            "name": "Playwright",
            "description": "Official Microsoft browser automation MCP for navigation, interaction and screenshots.",
            "transport": "stdio",
            "command": _npx("-y", "@playwright/mcp@latest", "--headless"),
            "requires": "Node.js 20+ / npx",
            "capabilities": ["browser", "navigation", "web_automation", "screenshot"],
            "auto_route": False,
        },
        {
            "id": "github",
            "name": "GitHub",
            "description": "GitHub's official MCP server for repositories, issues, pull requests and Actions.",
            "transport": "stdio",
            "command": f"{_python()} -m agentie.mcp_github_wrapper",
            "requires": "Docker · GitHub OAuth or GITHUB_PERSONAL_ACCESS_TOKEN",
            "capabilities": ["github", "repositories", "issues", "pull_requests", "actions"],
            "auto_route": True,
        },
        {
            "id": "memory",
            "name": "Memory",
            "description": "Knowledge-graph memory for entities, observations and relations.",
            "transport": "stdio",
            "command": _npx("-y", "@modelcontextprotocol/server-memory"),
            "requires": "Node.js / npx",
            "capabilities": ["knowledge_graph", "entities", "relations", "memory"],
            "auto_route": True,
        },
        {
            "id": "sequential-thinking",
            "name": "Sequential Thinking",
            "description": "Structured multi-step problem solving and reflective reasoning.",
            "transport": "stdio",
            "command": _npx("-y", "@modelcontextprotocol/server-sequential-thinking"),
            "requires": "Node.js / npx",
            "capabilities": ["reasoning", "planning", "sequential_thinking"],
            "auto_route": True,
        },
        {
            "id": "fetch",
            "name": "Fetch",
            "description": "Fetch and convert web content through an MCP server.",
            "transport": "stdio",
            "command": "uvx mcp-server-fetch",
            "requires": "uv / uvx",
            "capabilities": ["url_fetch", "web_page", "web_content"],
            "auto_route": True,
        },
        {
            "id": "time-mcp",
            "name": "Time",
            "description": "Timezone-aware time queries and timezone conversion.",
            "transport": "stdio",
            "command": "uvx mcp-server-time",
            "requires": "uv / uvx",
            "capabilities": ["timezone", "time_conversion"],
            "auto_route": False,
        },
        {
            "id": "git",
            "name": "Git",
            "description": "Read, search and manipulate the current local Git repository.",
            "transport": "stdio",
            "command": f'uvx mcp-server-git --repository "{_repo_path()}"',
            "requires": "uv / uvx",
            "capabilities": ["git", "repository", "commit", "branch", "diff", "log"],
            "auto_route": True,
        },
        {
            "id": "everything",
            "name": "Everything",
            "description": "Official MCP reference/test server exposing tools, resources and prompts.",
            "transport": "stdio",
            "command": _npx("-y", "@modelcontextprotocol/server-everything"),
            "requires": "Node.js / npx",
            "capabilities": ["mcp_testing", "tools", "resources", "prompts"],
            "auto_route": False,
        },
    ]


def preset_by_id(preset_id: str) -> dict[str, Any] | None:
    needle = str(preset_id or "").strip().lower()
    for item in presets():
        if item["id"] == needle:
            return item
    return None


def registration_command(preset_id: str) -> str | None:
    item = preset_by_id(preset_id)
    if not item:
        return None
    return f"Add MCP server {item['id']} using {item['command']}"
