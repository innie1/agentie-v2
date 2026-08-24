from __future__ import annotations

"""Failure-safety wrappers for first-time VirtualBox provisioning.

Only artifacts created by the failing attempt may be removed. Existing VDI,
legacy QCOW2 and QCOW2 backup files are never deleted here.
"""

from typing import Any

from agentie.core import company_computer_virtualbox as vbox
from agentie.core import company_computer_virtualbox_provisioning as provisioning

_ORIGINAL_ENSURE_DISK = vbox.ensure_disk
_ORIGINAL_CREATE_VM = vbox._create_vm


def ensure_disk(profile: dict[str, Any] | None = None):
    existed_before = vbox.DISK.exists()
    try:
        return _ORIGINAL_ENSURE_DISK(profile)
    except Exception:
        if not existed_before:
            vbox.DISK.unlink(missing_ok=True)
        raise


def _create_vm(profile: dict[str, Any]) -> None:
    existed_before = vbox._vm_exists()
    try:
        _ORIGINAL_CREATE_VM(profile)
    except Exception:
        if not existed_before and vbox._vm_exists():
            # Unregister only. Never use --delete here because the persistent
            # VDI may already contain migrated/user data.
            try:
                vbox._run(["unregistervm", vbox.VM_NAME], timeout=60)
            except Exception:
                pass
        raise


def register() -> None:
    vbox.ensure_disk = ensure_disk
    vbox._create_vm = _create_vm


register()
