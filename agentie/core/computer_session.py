from __future__ import annotations

from pathlib import Path
from typing import Any

from agentie.core.browser_monitor import LIVE_FRAME_FILE, _set_live_state, request_browser_stop


async def shutdown_computer() -> dict[str, Any]:
    """Power down the shared persistent Agentie Company Computer.

    The persistent guest disk remains intact, including browser profiles,
    cookies, downloads, installed applications and user files. This never
    powers down the host OS.
    """
    request_browser_stop()

    # Do not explicitly close the guest Chromium context through CDP: the VM owns
    # that browser and its persistent profile. Disconnect Agentie's Playwright
    # client after the guest has received its normal power-down request.
    from agentie.core.company_computer_backend import stop as stop_company_computer
    from agentie.core import browser_automation as browser

    result = stop_company_computer()
    async with browser._LOCK:
        try:
            if browser._PLAYWRIGHT is not None:
                await browser._PLAYWRIGHT.stop()
        except Exception:
            pass
        browser._PAGE = None
        browser._CONTEXT = None
        browser._BROWSER = None
        browser._PLAYWRIGHT = None
        browser._USING_COMPANY_COMPUTER = False

    try:
        Path(LIVE_FRAME_FILE).unlink(missing_ok=True)
    except Exception:
        pass
    _set_live_state(active=False, status="stopped", url="", detail="Agentie Computer stopped")
    return {
        "message": "Agentie Computer stopped. Persistent files and browser data were kept.",
        "card": {
            "type": "desktop_view",
            "app": "stopped",
            "mode": result.get("backend", "qemu"),
            "backend": result.get("backend", "qemu"),
            "state": result.get("state", "STOPPED"),
            "persistent": True,
        },
    }
