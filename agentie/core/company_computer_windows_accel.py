from __future__ import annotations

from typing import Any

from agentie.core import company_computer as computer


def _virtualbox_selected() -> bool:
    try:
        from agentie.core.company_computer_backend import backend_name
        return backend_name() == "virtualbox"
    except Exception:
        return False


_ORIGINAL_ACCELERATION = computer.acceleration

def acceleration(qemu: str | None = None, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Detect Windows WHPX without requiring an elevated DISM query.

    This remains available for the explicit AGENTIE_COMPUTER_BACKEND=qemu
    override. Windows normally uses VirtualBox now.
    """
    info = profile or computer.host_profile()
    if info.get("system") != "windows":
        return _ORIGINAL_ACCELERATION(qemu, info)

    binary = qemu or computer.qemu_binary(info)
    if not binary:
        return {
            "available": False,
            "accelerator": None,
            "reason": "QEMU is not installed yet.",
            "action": "Open Agentie Computer to let Agentie install or locate QEMU.",
        }

    supported = computer._accel_help(binary)
    whpx_enabled = computer._whpx_feature_enabled()
    if "whpx" in supported and (whpx_enabled or not computer.ALLOW_TCG):
        return {"available": True, "accelerator": "whpx", "reason": None, "action": None}

    if computer.ALLOW_TCG and "tcg" in supported:
        return {
            "available": True,
            "accelerator": "tcg",
            "compatibility_mode": True,
            "reason": "WHPX is not exposed by this QEMU build; explicit slow compatibility mode is enabled.",
            "action": None,
        }

    return {
        "available": False,
        "accelerator": "whpx",
        "reason": "This QEMU build does not expose WHPX acceleration.",
        "action": "Install or use a Windows QEMU build with WHPX support.",
    }

if not _virtualbox_selected():
    computer._ACTIVE_BACKEND = "qemu"
    computer.acceleration = acceleration
