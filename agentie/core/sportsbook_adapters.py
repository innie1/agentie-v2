from __future__ import annotations

"""Real sportsbook adapter contract for Agentie.

A sportsbook becomes available only after a real adapter registers here.
Adapters prepare slips, recheck exact live markets immediately before
submission, and submit only through Agentie's normal approval path.
"""

import threading
from abc import ABC, abstractmethod
from typing import Any


class SportsbookAdapterError(RuntimeError):
    pass


class SportsbookAdapter(ABC):
    """Site-specific Playwright/browser adapter contract."""

    sportsbook_id: str = ""
    display_name: str = ""

    def identity(self) -> dict[str, str]:
        sid = str(self.sportsbook_id or "").strip().lower()
        if not sid:
            raise SportsbookAdapterError("Sportsbook adapter is missing sportsbook_id.")
        return {"id": sid, "name": str(self.display_name or sid).strip() or sid}

    def diagnostics(self) -> dict[str, Any]:
        """Optional non-secret runtime properties surfaced in betting status."""
        return {}

    @abstractmethod
    async def prepare_bet(self, leg: dict[str, Any]) -> dict[str, Any]:
        """Open/fill the sportsbook slip without submitting the wager."""
        raise NotImplementedError

    @abstractmethod
    async def recheck_bet(self, prepared: dict[str, Any]) -> dict[str, Any]:
        """Return the current odds/availability/limit for the prepared leg."""
        raise NotImplementedError

    @abstractmethod
    async def submit_bet(self, prepared: dict[str, Any]) -> dict[str, Any]:
        """Submit the already prepared and freshly rechecked leg."""
        raise NotImplementedError

    async def abandon_prepared_bet(self, prepared: dict[str, Any]) -> None:
        """Best-effort cleanup when a plan is aborted before submission."""
        return None


_LOCK = threading.RLock()
_ADAPTERS: dict[str, SportsbookAdapter] = {}


def register_adapter(adapter: SportsbookAdapter) -> dict[str, str]:
    identity = adapter.identity()
    with _LOCK:
        _ADAPTERS[identity["id"]] = adapter
    return identity


def unregister_adapter(sportsbook_id: str) -> bool:
    sid = str(sportsbook_id or "").strip().lower()
    with _LOCK:
        return _ADAPTERS.pop(sid, None) is not None


def get_adapter(sportsbook_id: str) -> SportsbookAdapter | None:
    sid = str(sportsbook_id or "").strip().lower()
    with _LOCK:
        return _ADAPTERS.get(sid)


def require_adapter(sportsbook_id: str) -> SportsbookAdapter:
    adapter = get_adapter(sportsbook_id)
    if adapter is None:
        raise SportsbookAdapterError(
            f"Sportsbook '{sportsbook_id}' is not connected. Agentie will not simulate a live betting adapter."
        )
    return adapter


def list_adapters() -> list[dict[str, Any]]:
    with _LOCK:
        adapters = list(_ADAPTERS.values())
    out: list[dict[str, Any]] = []
    for adapter in adapters:
        item: dict[str, Any] = dict(adapter.identity())
        try:
            diagnostics = adapter.diagnostics()
            if isinstance(diagnostics, dict) and diagnostics:
                item["diagnostics"] = diagnostics
        except Exception as exc:
            item["diagnostics"] = {"status": "diagnostics_unavailable", "detail": str(exc)[:200]}
        out.append(item)
    return out
