from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from typing import Any

from agentie.core import company_computer_backend as computer

WORKSPACE = Path.cwd() / "workspace"
GUEST_HOME = PurePosixPath("/home/agentie")
GUEST_INBOX = GUEST_HOME / "Agentie Inbox"
GUEST_EXPORTS = GUEST_HOME / "Agentie Exports"
MAX_TRANSFER_BYTES = 100 * 1024 * 1024
CHUNK_BYTES = 12 * 1024


def _safe_host_file(name_or_path: str) -> Path:
    raw = str(name_or_path or "").strip().strip('"\'')
    if not raw:
        raise ValueError("A workspace file is required.")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = WORKSPACE / candidate
    resolved = candidate.resolve()
    root = WORKSPACE.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("Only files inside the Agentie workspace can be transferred to the Company Computer.")
    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(resolved.name)
    if resolved.stat().st_size > MAX_TRANSFER_BYTES:
        raise ValueError("Company Computer file transfer is limited to 100 MB per file.")
    return resolved


def _safe_guest_path(path: str, *, default_dir: PurePosixPath) -> PurePosixPath:
    raw = str(path or "").strip()
    if not raw:
        raise ValueError("A guest file path is required.")
    candidate = PurePosixPath(raw)
    if not candidate.is_absolute():
        candidate = default_dir / candidate
    if ".." in candidate.parts:
        raise ValueError("Guest path traversal is not allowed.")
    if candidate != GUEST_HOME and GUEST_HOME not in candidate.parents:
        raise ValueError("Agentie file transfer is restricted to /home/agentie.")
    return candidate


def _ensure_guest_dir(path: PurePosixPath) -> None:
    result = computer.guest_exec(["/bin/mkdir", "-p", str(path)], timeout=20)
    if int(result.get("exitcode") or 0) != 0:
        raise computer.ComputerError(f"Could not prepare guest folder: {path}")
    computer.guest_exec(["/bin/chown", "-R", "agentie:agentie", str(path)], timeout=20)


def upload_workspace_file(name_or_path: str, guest_path: str | None = None) -> dict[str, Any]:
    """Copy a real Agentie workspace file into the selected persistent guest."""
    computer.start()
    source = _safe_host_file(name_or_path)
    destination = _safe_guest_path(guest_path or source.name, default_dir=GUEST_INBOX)
    _ensure_guest_dir(destination.parent)
    written = computer.guest_upload(source, str(destination), chunk_bytes=CHUNK_BYTES)
    computer.guest_exec(["/bin/chown", "agentie:agentie", str(destination)], timeout=20)
    computer.touch_activity()
    return {"name": source.name, "host_path": str(source), "guest_path": str(destination), "size_bytes": written, "persistent": True}


def download_guest_file(guest_path: str, workspace_name: str | None = None) -> dict[str, Any]:
    """Copy a real persistent guest file into Agentie's host workspace."""
    computer.start()
    source = _safe_guest_path(guest_path, default_dir=GUEST_EXPORTS)
    filename = str(workspace_name or source.name).strip()
    if not filename or Path(filename).name != filename:
        raise ValueError("Export filename must be a simple workspace filename.")
    destination = (WORKSPACE / filename).resolve()
    root = WORKSPACE.resolve()
    if root not in destination.parents:
        raise ValueError("Export destination must remain inside the Agentie workspace.")
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + ".part")
    try:
        total = computer.guest_download(str(source), temp, max_bytes=MAX_TRANSFER_BYTES, chunk_bytes=CHUNK_BYTES)
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)
    computer.touch_activity()
    return {"name": destination.name, "host_path": str(destination), "guest_path": str(source), "size_bytes": total, "persistent": True}
