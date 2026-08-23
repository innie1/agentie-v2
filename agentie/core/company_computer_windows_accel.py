from __future__ import annotations

from typing import Any

from agentie.core import company_computer as computer

_ORIGINAL_ACCELERATION = computer.acceleration


def acceleration(qemu: str | None = None, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Detect Windows WHPX without requiring an elevated DISM query.

    Agentie normally runs unelevated. DISM /Online /Get-FeatureInfo can return
    access denied in that context even when Windows Hypervisor Platform is
    enabled, which previously caused a false "WHPX is unavailable" block.

    QEMU's own accelerator list is the authoritative preflight check. The real
    VM launch remains the final capability test and will surface QEMU's actual
    startup error if the Windows hypervisor cannot initialize.
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
    if "whpx" in supported:
        return {
            "available": True,
            "accelerator": "whpx",
            "reason": None,
            "action": None,
        }

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


# Patch the shared Company Computer module once this compatibility module is
# imported. Existing start()/status() functions resolve `acceleration` through
# the module globals at call time, so all callers immediately use this fix.
computer.acceleration = acceleration
