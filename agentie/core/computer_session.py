from __future__ import annotations

from pathlib import Path
from typing import Any

from agentie.core.browser_monitor import LIVE_FRAME_FILE, _set_live_state, request_browser_stop


async def shutdown_computer() -> dict[str, Any]:
    """Stop the persistent Agentie virtual-computer browser session.

    This powers down Agentie's own computer session, not the host OS. A later
    browser/desktop request lazily starts a fresh browser session again.
    """
    request_browser_stop()

    # Import lazily to avoid a module cycle at import time.
    from agentie.core import browser_automation as browser

    async with browser._LOCK:
        try:
            if browser._PAGE is not None and not browser._PAGE.is_closed():
                await browser._PAGE.close()
        except Exception:
            pass
        try:
            if browser._CONTEXT is not None:
                await browser._CONTEXT.close()
        except Exception:
            pass
        try:
            if browser._BROWSER is not None and browser._BROWSER.is_connected():
                await browser._BROWSER.close()
        except Exception:
            pass
        try:
            if browser._PLAYWRIGHT is not None:
                await browser._PLAYWRIGHT.stop()
        except Exception:
            pass

        browser._PAGE = None
        browser._CONTEXT = None
        browser._BROWSER = None
        browser._PLAYWRIGHT = None

    try:
        Path(LIVE_FRAME_FILE).unlink(missing_ok=True)
    except Exception:
        pass
    _set_live_state(active=False, status="stopped", url="", detail="Agentie Computer stopped")
    return {
        "message": "Agentie Computer stopped.",
        "card": {"type": "desktop_view", "app": "stopped"},
    }
