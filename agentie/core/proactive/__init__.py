"""Proactive follow-up engine.

Closes the "nudge a stalled handoff without being asked" gap: the rest of
Agentie's team orchestration only acts when a user or agent explicitly issues
a command (delegate, work together, retry). Nothing previously re-engaged a
handoff that just sat in ``queued``/``working`` with no progress.

Design constraint: offline-first. Nudging is pure local JSON state (no model
call, no network). Escalation only calls a real agent when the stalled job
was owned by a delegate-capable manager agent, and that call goes through
Agentie's existing local/auto/powerful router (agentie.core.model_routing),
so it still prefers the local model when one is configured. Jobs started
directly by the user (not by a manager) are never auto-escalated to a model
call; they only publish an event so an event-driven routine or the UI can
surface it.
"""
from agentie.core.proactive.stale_handoff_monitor import StaleHandoffConfig, scan_and_nudge

__all__ = ["StaleHandoffConfig", "scan_and_nudge"]
