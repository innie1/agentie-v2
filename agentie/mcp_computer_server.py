from __future__ import annotations

from typing import Any

from agentie.core import company_computer_backend as computer
from agentie.core.company_computer_commands import launch_guest_app, run_guest_command
from agentie.core.company_computer_files import download_guest_file, upload_workspace_file
from agentie.mcp_runtime import make_server, require_approval

SERVER_ID = "agentie-computer"
mcp = make_server("Agentie Company Computer")


@mcp.tool()
def get_computer_status() -> dict[str, Any]:
    """Get the state and selected backend of the persistent Company Computer."""
    return computer.status()


@mcp.tool()
def start_company_computer(approval_id: str = "") -> dict[str, Any]:
    """Start or resume the persistent Company Computer after approval."""
    pending = require_approval(
        SERVER_ID,
        "start_company_computer",
        {"backend": computer.selected_backend()},
        "Start the persistent Agentie Company Computer and allocate host resources.",
        approval_id,
    )
    if pending:
        return pending
    return computer.start()


@mcp.tool()
def stop_company_computer(approval_id: str = "") -> dict[str, Any]:
    """Stop the Company Computer after approval without deleting its persistent disk."""
    pending = require_approval(
        SERVER_ID,
        "stop_company_computer",
        {"backend": computer.selected_backend()},
        "Stop the Agentie Company Computer. Persistent storage is preserved.",
        approval_id,
    )
    if pending:
        return pending
    return computer.stop()


@mcp.tool()
def suspend_company_computer(approval_id: str = "") -> dict[str, Any]:
    """Suspend the Company Computer after approval while keeping persistent state."""
    pending = require_approval(
        SERVER_ID,
        "suspend_company_computer",
        {"backend": computer.selected_backend()},
        "Suspend the Agentie Company Computer and release active resources.",
        approval_id,
    )
    if pending:
        return pending
    return computer.suspend()


@mcp.tool()
def resume_company_computer(approval_id: str = "") -> dict[str, Any]:
    """Resume a suspended Company Computer after approval."""
    pending = require_approval(
        SERVER_ID,
        "resume_company_computer",
        {"backend": computer.selected_backend()},
        "Resume the persistent Agentie Company Computer.",
        approval_id,
    )
    if pending:
        return pending
    return computer.resume()


@mcp.tool()
def run_company_computer_command(
    command: str,
    session_id: str = "mcp-computer",
    timeout: int = 120,
) -> dict[str, Any]:
    """Run a command inside the real persistent guest.

    The existing Company Computer command layer automatically creates an
    approval request for destructive, system-changing, or external-write
    commands; ordinary guest commands can run directly.
    """
    return run_guest_command(command, session_id, timeout=max(1, min(int(timeout), 300)))


@mcp.tool()
def open_company_computer_app(app: str, session_id: str = "mcp-computer") -> dict[str, Any]:
    """Open Chromium, Terminal, or File Manager inside the persistent guest."""
    return launch_guest_app(app, session_id)


@mcp.tool()
def copy_workspace_file_to_computer(
    workspace_path: str,
    guest_path: str = "",
    approval_id: str = "",
) -> dict[str, Any]:
    """Copy a file from Agentie's confined workspace into the persistent guest."""
    payload = {"workspace_path": workspace_path, "guest_path": guest_path}
    pending = require_approval(
        SERVER_ID,
        "copy_workspace_file_to_computer",
        payload,
        "Copy a persistent workspace file into the Agentie Company Computer.",
        approval_id,
    )
    if pending:
        return pending
    return upload_workspace_file(workspace_path, guest_path or None)


@mcp.tool()
def copy_computer_file_to_workspace(
    guest_path: str,
    workspace_name: str = "",
    approval_id: str = "",
) -> dict[str, Any]:
    """Copy a file from /home/agentie in the guest into Agentie's workspace."""
    payload = {"guest_path": guest_path, "workspace_name": workspace_name}
    pending = require_approval(
        SERVER_ID,
        "copy_computer_file_to_workspace",
        payload,
        "Export a file from the Agentie Company Computer into the host workspace.",
        approval_id,
    )
    if pending:
        return pending
    return download_guest_file(guest_path, workspace_name or None)


if __name__ == "__main__":
    mcp.run(transport="stdio")
