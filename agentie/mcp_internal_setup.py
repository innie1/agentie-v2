from __future__ import annotations

import os
from typing import Any

from agentie.core.mcp_client import add_local_server

INTERNAL_SERVERS = {
    "agentie-company": "agentie.mcp_company_server",
    "agentie-computer": "agentie.mcp_computer_server",
    "agentie-channels": "agentie.mcp_channels_server",
    "agentie-business-data": "agentie.mcp_business_data_server",
    "agentie-workspace": "agentie.mcp_workspace_server",
}


def _python_command(module: str) -> str:
    launcher = "py" if os.name == "nt" else "python"
    return f"{launcher} -m {module}"


def register_internal_servers() -> list[dict[str, Any]]:
    """Register Agentie's built-in MCP servers in the normal MCP client store.

    Registration enables the servers as MCP endpoints but does not bypass
    Agentie's per-agent capability policy or action-level approval system.
    """
    return [
        add_local_server(name, _python_command(module))
        for name, module in INTERNAL_SERVERS.items()
    ]


def main() -> None:
    rows = register_internal_servers()
    print(f"Registered {len(rows)} Agentie internal MCP servers:")
    for row in rows:
        print(f"- {row.get('name')}: {row.get('command')} {' '.join(row.get('args') or [])}")


if __name__ == "__main__":
    main()
