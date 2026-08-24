from __future__ import annotations

"""VirtualBox Guest Additions command transport for Company Computer.

VBoxManage's --exe option supplies argv[0]; only command arguments belong after
`--`. Keeping this adapter separate makes the transport contract testable and
prevents QEMU Guest Agent compatibility code from leaking into Windows.
"""

import base64
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from agentie.core import company_computer_virtualbox as vbox


def guest_exec(command: list[str], timeout: int = 30) -> dict[str, Any]:
    if not command:
        raise vbox.ComputerError("Guest command cannot be empty.")
    username, password = vbox.guest_credentials()
    password_file: Path | None = None
    try:
        handle = tempfile.NamedTemporaryFile(
            "w", delete=False, encoding="utf-8", dir=str(vbox.ROOT), prefix=".vbox-pass-"
        )
        password_file = Path(handle.name)
        handle.write(password)
        handle.close()
        try:
            os.chmod(password_file, 0o600)
        except OSError:
            pass

        args = [
            "guestcontrol", vbox.VM_NAME, "run",
            "--exe", command[0],
            "--username", username,
            "--passwordfile", str(password_file),
            "--timeout", str(max(1000, int(timeout * 1000))),
            "--wait-stdout", "--wait-stderr",
        ]
        if len(command) > 1:
            args.extend(["--", *command[1:]])
        proc = vbox._run(args, timeout=max(10, int(timeout) + 10))
        return {
            "exitcode": int(proc.returncode),
            "out-data": base64.b64encode((proc.stdout or "").encode("utf-8")).decode("ascii"),
            "err-data": base64.b64encode((proc.stderr or "").encode("utf-8")).decode("ascii"),
        }
    except subprocess.TimeoutExpired as exc:
        raise vbox.ComputerError("VirtualBox guest command timed out.") from exc
    finally:
        if password_file is not None:
            password_file.unlink(missing_ok=True)


def register() -> None:
    vbox.guest_exec = guest_exec


register()
