from __future__ import annotations

import json
import socket
import time
from typing import Any

from agentie.core import company_computer as computer


def _module_is_virtualbox_compat() -> bool:
    return str(getattr(computer, "_ACTIVE_BACKEND", "")).lower() == "virtualbox"


if not _module_is_virtualbox_compat():
    from agentie.core import company_computer_resume_compat as _resume_compat  # resumes paused VM before QGA use

    def _qga_request(payload: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
        """Send one command over the QEMU Guest Agent TCP chardev."""
        if not computer._port_open(computer.QGA_PORT):
            raise computer.ComputerError("Guest automation channel is not ready yet.")
        with socket.create_connection(("127.0.0.1", computer.QGA_PORT), timeout=timeout) as sock:
            sock.settimeout(timeout)
            file = sock.makefile("rwb", buffering=0)
            file.write(json.dumps(payload).encode("utf-8") + b"\n")
            deadline = time.time() + timeout
            while time.time() < deadline:
                line = file.readline()
                if not line:
                    break
                try:
                    item = json.loads(line.decode("utf-8", "replace"))
                except json.JSONDecodeError:
                    continue
                if "return" in item or "error" in item:
                    return item
        raise computer.ComputerError("Guest automation command timed out.")


    def guest_exec(command: list[str], timeout: int = 60) -> dict[str, Any]:
        """Execute a command inside the persistent Linux guest through QGA."""
        if not command:
            raise ValueError("Guest command is required.")
        response = _qga_request(
            {
                "execute": "guest-exec",
                "arguments": {
                    "path": command[0],
                    "arg": command[1:],
                    "capture-output": True,
                },
            },
            timeout=min(max(float(timeout), 10.0), 60.0),
        )
        if response.get("error"):
            raise computer.ComputerError(str(response["error"]))
        pid = int((response.get("return") or {}).get("pid") or 0)
        if not pid:
            raise computer.ComputerError("Guest command did not start.")

        deadline = time.time() + max(1, int(timeout))
        while time.time() < deadline:
            item = _qga_request(
                {"execute": "guest-exec-status", "arguments": {"pid": pid}},
                timeout=min(10.0, max(1.0, deadline - time.time())),
            )
            if item.get("error"):
                raise computer.ComputerError(str(item["error"]))
            result = item.get("return") or {}
            if result.get("exited"):
                computer.touch_activity()
                return result
            time.sleep(0.2)
        raise computer.ComputerError("Guest command timed out.")


    def qmp_input(events: list[dict[str, Any]]) -> None:
        """Send raw input events through QEMU's QMP input-send-event command."""
        result = computer._qmp_command("input-send-event", {"events": events})
        if result.get("error"):
            raise computer.ComputerError(str(result["error"]))
        computer.touch_activity()


    computer._qga_request = _qga_request
    computer.guest_exec = guest_exec
    computer.qmp_input = qmp_input
