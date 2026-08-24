from __future__ import annotations

from typing import Any

from agentie.core import company_computer as computer


def _virtualbox_selected() -> bool:
    try:
        from agentie.core.company_computer_backend import backend_name
        return backend_name() == "virtualbox"
    except Exception:
        return False


if _virtualbox_selected():
    # Keep the legacy company_computer module API compatible for modules that
    # intentionally hold the module object rather than the new backend facade.
    from agentie.core import company_computer_virtualbox as _vbox
    from agentie.core import company_computer_virtualbox_provisioning as _vbox_provisioning  # noqa: F401

    for _name in (
        "prepare", "start", "stop", "suspend", "resume", "status",
        "acquire_agent", "acquire_for_session", "handoff_agent",
        "request_user_takeover", "request_user_takeover_for_session",
        "acquire_user", "continue_agent", "release_control", "touch_activity",
        "display_url", "guest_exec", "_row", "_update", "_session_agent_id",
    ):
        setattr(computer, _name, getattr(_vbox, _name))
else:
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
        if "whpx" in supported:
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

    computer.acceleration = acceleration
