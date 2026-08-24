from __future__ import annotations

"""Agentie sports betting engine.

The engine supports paper tracking, arbitrage maths, +EV/value analysis, durable
execution plans and approval-gated live submission.  It deliberately contains
no sportsbook-specific selectors; those live in real adapters registered in
``sportsbook_adapters``.
"""

import asyncio
import hashlib
import json
import math
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Coroutine

from agentie.core.sportsbook_adapters import list_adapters, require_adapter

WORKSPACE = Path.cwd() / "workspace"
STATE = WORKSPACE / "sports_betting.json"
_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _empty_state() -> dict[str, Any]:
    return {"plans": [], "bets": [], "executions": []}


def _load() -> dict[str, Any]:
    try:
        if not STATE.exists():
            return _empty_state()
        data = json.loads(STATE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _empty_state()
        for key in ("plans", "bets", "executions"):
            if not isinstance(data.get(key), list):
                data[key] = []
        return data
    except Exception:
        return _empty_state()


def _save(data: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _decimal(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite.")
    return number


def decimal_odds(value: Any) -> float:
    odds = _decimal(value, "Decimal odds")
    if odds <= 1.0:
        raise ValueError("Decimal odds must be greater than 1.0.")
    return odds


def implied_probability(odds: Any) -> float:
    return 1.0 / decimal_odds(odds)


def expected_value(odds: Any, true_probability: Any) -> float:
    price = decimal_odds(odds)
    probability = _decimal(true_probability, "True probability")
    if not 0.0 <= probability <= 1.0:
        raise ValueError("True probability must be between 0 and 1.")
    return probability * price - 1.0


def kelly_fraction(odds: Any, true_probability: Any) -> float:
    price = decimal_odds(odds)
    probability = _decimal(true_probability, "True probability")
    if not 0.0 <= probability <= 1.0:
        raise ValueError("True probability must be between 0 and 1.")
    edge = probability * price - 1.0
    return max(0.0, edge / (price - 1.0))


def analyze_value_bet(
    *,
    odds: Any,
    true_probability: Any,
    bankroll: Any,
    kelly_multiplier: float = 0.25,
    max_bankroll_fraction: float = 0.02,
) -> dict[str, Any]:
    price = decimal_odds(odds)
    probability = _decimal(true_probability, "True probability")
    bank = _decimal(bankroll, "Bankroll")
    if bank < 0:
        raise ValueError("Bankroll cannot be negative.")
    if not 0.0 <= probability <= 1.0:
        raise ValueError("True probability must be between 0 and 1.")
    if not 0.0 <= kelly_multiplier <= 1.0:
        raise ValueError("Kelly multiplier must be between 0 and 1.")
    if not 0.0 <= max_bankroll_fraction <= 1.0:
        raise ValueError("Maximum bankroll fraction must be between 0 and 1.")
    implied = 1.0 / price
    ev = probability * price - 1.0
    full_kelly = kelly_fraction(price, probability)
    stake_fraction = min(full_kelly * kelly_multiplier, max_bankroll_fraction) if ev > 0 else 0.0
    return {
        "type": "value_bet_analysis",
        "odds": round(price, 6),
        "true_probability": round(probability, 8),
        "implied_probability": round(implied, 8),
        "probability_edge": round(probability - implied, 8),
        "expected_value_per_unit": round(ev, 8),
        "expected_value_percent": round(ev * 100.0, 4),
        "positive_ev": ev > 0,
        "full_kelly_fraction": round(full_kelly, 8),
        "recommended_fraction": round(stake_fraction, 8),
        "recommended_stake": round(bank * stake_fraction, 2),
        "bankroll": round(bank, 2),
    }


def _market_key(leg: dict[str, Any]) -> tuple[str, str]:
    event = " ".join(str(leg.get("event") or "").casefold().split())
    market = " ".join(str(leg.get("market") or "").casefold().split())
    return event, market


def detect_arbitrage(legs: list[dict[str, Any]], bankroll: Any) -> dict[str, Any]:
    if len(legs) < 2:
        raise ValueError("Arbitrage analysis needs at least two mutually exclusive outcomes.")
    bank = _decimal(bankroll, "Bankroll")
    if bank <= 0:
        raise ValueError("Bankroll must be greater than zero.")
    market_keys = {_market_key(leg) for leg in legs}
    if len(market_keys) != 1:
        raise ValueError("All arbitrage legs must refer to the same event and market.")
    selections = [" ".join(str(leg.get("selection") or "").casefold().split()) for leg in legs]
    if any(not value for value in selections) or len(set(selections)) != len(selections):
        raise ValueError("Arbitrage legs must contain unique selections.")

    inverse_sum = 0.0
    prices: list[float] = []
    for leg in legs:
        price = decimal_odds(leg.get("odds"))
        prices.append(price)
        inverse_sum += 1.0 / price

    is_arbitrage = inverse_sum < 1.0
    payout = bank / inverse_sum
    result_legs = []
    for leg, price in zip(legs, prices):
        stake = bank * ((1.0 / price) / inverse_sum)
        result_legs.append(
            {
                **dict(leg),
                "odds": round(price, 6),
                "stake": round(stake, 2),
                "target_payout": round(stake * price, 2),
            }
        )
    profit = payout - bank if is_arbitrage else 0.0
    return {
        "type": "arbitrage_analysis",
        "event": legs[0].get("event"),
        "market": legs[0].get("market"),
        "inverse_probability_sum": round(inverse_sum, 8),
        "arbitrage": is_arbitrage,
        "margin_percent": round((1.0 - inverse_sum) * 100.0, 4),
        "bankroll": round(bank, 2),
        "target_payout": round(payout, 2) if is_arbitrage else None,
        "expected_profit": round(profit, 2),
        "expected_profit_percent": round((profit / bank) * 100.0, 4) if is_arbitrage else 0.0,
        "legs": result_legs,
    }


def create_execution_plan(
    *,
    strategy: str,
    legs: list[dict[str, Any]],
    expected_profit: float | None = None,
    notes: str = "",
) -> dict[str, Any]:
    if not legs:
        raise ValueError("Execution plan requires at least one betting leg.")
    clean_legs = []
    total_stake = 0.0
    for leg in legs:
        sportsbook = str(leg.get("sportsbook") or "").strip().lower()
        if not sportsbook:
            raise ValueError("Every live betting leg must name a sportsbook adapter.")
        stake = _decimal(leg.get("stake"), "Stake")
        if stake <= 0:
            raise ValueError("Every live betting stake must be greater than zero.")
        price = decimal_odds(leg.get("odds"))
        total_stake += stake
        clean_legs.append(
            {
                "sportsbook": sportsbook,
                "event": str(leg.get("event") or "").strip(),
                "market": str(leg.get("market") or "").strip(),
                "selection": str(leg.get("selection") or "").strip(),
                "odds": round(price, 6),
                "stake": round(stake, 2),
                **({"currency": str(leg.get("currency")).upper()} if leg.get("currency") else {}),
            }
        )
    plan = {
        "id": "betplan_" + uuid.uuid4().hex[:12],
        "strategy": str(strategy or "manual").strip().lower() or "manual",
        "legs": clean_legs,
        "total_stake": round(total_stake, 2),
        "expected_profit": round(float(expected_profit), 2) if expected_profit is not None else None,
        "notes": str(notes or "")[:1000],
        "status": "draft",
        "created_at": _now(),
        "updated_at": _now(),
    }
    with _LOCK:
        data = _load()
        data["plans"].append(plan)
        _save(data)
    return dict(plan)


def get_execution_plan(plan_id: str) -> dict[str, Any] | None:
    key = str(plan_id or "").strip()
    with _LOCK:
        for plan in _load()["plans"]:
            if plan.get("id") == key:
                return dict(plan)
    return None


def _replace_plan(plan: dict[str, Any]) -> None:
    with _LOCK:
        data = _load()
        for index, existing in enumerate(data["plans"]):
            if existing.get("id") == plan.get("id"):
                data["plans"][index] = plan
                _save(data)
                return
        data["plans"].append(plan)
        _save(data)


def _snapshot_hash(plan: dict[str, Any]) -> str:
    payload = json.dumps(
        {"id": plan.get("id"), "legs": plan.get("legs"), "total_stake": plan.get("total_stake")},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:20]


def _run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run a coroutine safely from Agentie's synchronous approval/runtime paths."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    result: dict[str, Any] = {}
    error: list[BaseException] = []

    def worker() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - only when caller already has an event loop
            error.append(exc)

    thread = threading.Thread(target=worker, name="agentie-sports-betting", daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result.get("value")


async def _prepare_plan_async(plan: dict[str, Any]) -> dict[str, Any]:
    async def prepare(leg: dict[str, Any]) -> dict[str, Any]:
        adapter = require_adapter(leg["sportsbook"])
        prepared = await adapter.prepare_bet(dict(leg))
        if not isinstance(prepared, dict):
            raise RuntimeError(f"{leg['sportsbook']} adapter did not return a prepared bet payload.")
        return {"leg": dict(leg), "prepared": prepared}

    prepared = await asyncio.gather(*(prepare(leg) for leg in plan["legs"]))
    updated = dict(plan)
    updated["prepared"] = prepared
    updated["status"] = "prepared"
    updated["snapshot_hash"] = _snapshot_hash(updated)
    updated["updated_at"] = _now()
    _replace_plan(updated)
    return updated


def prepare_execution_plan(plan_id: str) -> dict[str, Any]:
    plan = get_execution_plan(plan_id)
    if not plan:
        raise ValueError("Betting execution plan was not found.")
    if plan.get("status") in {"submitted", "partial"}:
        raise ValueError("This betting execution plan has already been submitted.")
    missing = sorted({leg["sportsbook"] for leg in plan["legs"] if require_adapter_or_none(leg["sportsbook"]) is None})
    if missing:
        raise RuntimeError(
            "Live betting is unavailable for: " + ", ".join(missing) + ". Install/test real sportsbook adapters first."
        )
    return _run_async(_prepare_plan_async(plan))


def require_adapter_or_none(sportsbook_id: str):
    try:
        return require_adapter(sportsbook_id)
    except Exception:
        return None


def request_execution_approval(plan_id: str) -> dict[str, Any]:
    plan = prepare_execution_plan(plan_id)
    from agentie.tools.approval_tools import create_approval

    lines = []
    for leg in plan["legs"]:
        lines.append(
            f"{leg['sportsbook']}: {leg['selection']} @ {leg['odds']} — stake {leg['stake']:.2f}"
        )
    profit = plan.get("expected_profit")
    reason = (
        f"Place {len(plan['legs'])} real-money sports bet(s) with total stake {plan['total_stake']:.2f}"
        + (f" and expected strategy profit {profit:.2f}" if profit is not None else "")
        + ". Agentie will recheck every leg before submitting. "
        + " | ".join(lines)
    )
    action = f"sports_bet_submit:{plan['id']}:{plan['snapshot_hash']}"
    approval = create_approval(
        action,
        reason,
        {
            "kind": "sports_bet_submit",
            "plan_id": plan["id"],
            "snapshot_hash": plan["snapshot_hash"],
            "strategy": plan.get("strategy"),
            "total_stake": plan.get("total_stake"),
            "expected_profit": plan.get("expected_profit"),
            "legs": plan.get("legs"),
        },
    )
    updated = dict(plan)
    updated["status"] = "awaiting_approval"
    updated["approval_id"] = approval["id"]
    updated["updated_at"] = _now()
    _replace_plan(updated)
    return approval


async def _abandon_all(plan: dict[str, Any]) -> None:
    tasks = []
    for item in plan.get("prepared") or []:
        leg = item.get("leg") or {}
        adapter = require_adapter_or_none(leg.get("sportsbook"))
        if adapter is not None:
            tasks.append(adapter.abandon_prepared_bet(item.get("prepared") or {}))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _execute_plan_async(plan: dict[str, Any]) -> dict[str, Any]:
    prepared_items = list(plan.get("prepared") or [])
    if len(prepared_items) != len(plan.get("legs") or []):
        raise ValueError("Betting plan is not fully prepared.")

    async def recheck(item: dict[str, Any]) -> dict[str, Any]:
        leg = item["leg"]
        adapter = require_adapter(leg["sportsbook"])
        current = await adapter.recheck_bet(item["prepared"])
        return {"leg": leg, "current": current}

    checks = await asyncio.gather(*(recheck(item) for item in prepared_items))
    changes: list[dict[str, Any]] = []
    for checked in checks:
        leg = checked["leg"]
        current = checked.get("current") or {}
        available = bool(current.get("available", True))
        current_odds = current.get("odds", leg["odds"])
        try:
            current_odds_float = decimal_odds(current_odds)
        except Exception:
            current_odds_float = None
        max_stake = current.get("max_stake")
        if not available:
            changes.append({"sportsbook": leg["sportsbook"], "selection": leg["selection"], "change": "market unavailable"})
        elif current_odds_float is None or abs(current_odds_float - float(leg["odds"])) > 1e-9:
            changes.append(
                {
                    "sportsbook": leg["sportsbook"],
                    "selection": leg["selection"],
                    "change": "odds changed",
                    "before": leg["odds"],
                    "after": current_odds,
                }
            )
        elif max_stake is not None and float(max_stake) + 1e-9 < float(leg["stake"]):
            changes.append(
                {
                    "sportsbook": leg["sportsbook"],
                    "selection": leg["selection"],
                    "change": "stake limit changed",
                    "requested_stake": leg["stake"],
                    "max_stake": max_stake,
                }
            )

    if changes:
        await _abandon_all(plan)
        updated = dict(plan)
        updated["status"] = "changed"
        updated["changes"] = changes
        updated["updated_at"] = _now()
        _replace_plan(updated)
        result = {"status": "changed", "submitted": False, "plan_id": plan["id"], "changes": changes}
        _record_execution(result)
        return result

    async def submit(item: dict[str, Any]) -> dict[str, Any]:
        leg = item["leg"]
        adapter = require_adapter(leg["sportsbook"])
        try:
            response = await adapter.submit_bet(item["prepared"])
            return {"sportsbook": leg["sportsbook"], "selection": leg["selection"], "ok": True, "result": response}
        except Exception as exc:
            return {"sportsbook": leg["sportsbook"], "selection": leg["selection"], "ok": False, "error": str(exc)}

    submissions = await asyncio.gather(*(submit(item) for item in prepared_items))
    success = [item for item in submissions if item.get("ok")]
    status = "submitted" if len(success) == len(submissions) else "partial" if success else "failed"
    updated = dict(plan)
    updated["status"] = status
    updated["submission_results"] = submissions
    updated["updated_at"] = _now()
    _replace_plan(updated)
    result = {
        "status": status,
        "submitted": bool(success),
        "plan_id": plan["id"],
        "results": submissions,
        "partial_fill_warning": status == "partial",
    }
    _record_execution(result)
    return result


def _record_execution(result: dict[str, Any]) -> None:
    row = {"id": "betexec_" + uuid.uuid4().hex[:10], "at": _now(), **result}
    with _LOCK:
        data = _load()
        data["executions"].append(row)
        _save(data)


def execute_approved_plan(plan_id: str, *, expected_snapshot_hash: str | None = None) -> dict[str, Any]:
    plan = get_execution_plan(plan_id)
    if not plan:
        raise ValueError("Approved betting plan was not found.")
    if expected_snapshot_hash and plan.get("snapshot_hash") != expected_snapshot_hash:
        raise ValueError("Betting plan changed after approval was created. Nothing was submitted.")
    if plan.get("status") not in {"prepared", "awaiting_approval"}:
        raise ValueError(f"Betting plan cannot be submitted from status {plan.get('status')}.")
    return _run_async(_execute_plan_async(plan))


def record_bet(
    *,
    strategy: str,
    sportsbook: str,
    event: str,
    market: str,
    selection: str,
    odds: Any,
    stake: Any,
    mode: str = "paper",
) -> dict[str, Any]:
    price = decimal_odds(odds)
    amount = _decimal(stake, "Stake")
    if amount <= 0:
        raise ValueError("Stake must be greater than zero.")
    clean_mode = str(mode or "paper").strip().lower()
    if clean_mode not in {"paper", "real"}:
        raise ValueError("Bet mode must be paper or real.")
    row = {
        "id": "bet_" + uuid.uuid4().hex[:12],
        "strategy": str(strategy or "manual").strip().lower() or "manual",
        "sportsbook": str(sportsbook or "").strip(),
        "event": str(event or "").strip(),
        "market": str(market or "").strip(),
        "selection": str(selection or "").strip(),
        "odds": round(price, 6),
        "stake": round(amount, 2),
        "mode": clean_mode,
        "status": "open",
        "placed_at": _now(),
    }
    with _LOCK:
        data = _load()
        data["bets"].append(row)
        _save(data)
    return dict(row)


def settle_bet(bet_id: str, *, outcome: str, payout: Any | None = None) -> dict[str, Any]:
    clean_outcome = str(outcome or "").strip().lower()
    if clean_outcome not in {"won", "lost", "void"}:
        raise ValueError("Bet outcome must be won, lost or void.")
    with _LOCK:
        data = _load()
        row = next((item for item in data["bets"] if item.get("id") == bet_id), None)
        if not row:
            raise ValueError("Bet was not found.")
        if row.get("status") != "open":
            raise ValueError("Bet has already been settled.")
        stake = float(row["stake"])
        if clean_outcome == "won":
            paid = float(payout) if payout is not None else stake * float(row["odds"])
        elif clean_outcome == "void":
            paid = stake
        else:
            paid = 0.0
        row["status"] = clean_outcome
        row["payout"] = round(paid, 2)
        row["profit"] = round(paid - stake, 2)
        row["settled_at"] = _now()
        _save(data)
        return dict(row)


def performance(*, month: str | None = None, mode: str | None = None) -> dict[str, Any]:
    if month and not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError("Month must use YYYY-MM format.")
    clean_mode = str(mode or "").strip().lower() or None
    if clean_mode not in {None, "paper", "real"}:
        raise ValueError("Mode must be paper or real.")
    with _LOCK:
        bets = [dict(item) for item in _load()["bets"]]
    if month:
        bets = [item for item in bets if str(item.get("placed_at") or "").startswith(month)]
    if clean_mode:
        bets = [item for item in bets if item.get("mode") == clean_mode]
    settled = [item for item in bets if item.get("status") in {"won", "lost", "void"}]
    total_staked = sum(float(item.get("stake") or 0.0) for item in settled)
    profit = sum(float(item.get("profit") or 0.0) for item in settled)
    decisions = [item for item in settled if item.get("status") != "void"]
    wins = sum(1 for item in decisions if item.get("status") == "won")
    yield_pct = (profit / total_staked * 100.0) if total_staked else 0.0
    return {
        "type": "sports_betting_performance",
        "month": month,
        "mode": clean_mode or "all",
        "bets": len(bets),
        "settled": len(settled),
        "open": len([item for item in bets if item.get("status") == "open"]),
        "wins": wins,
        "losses": sum(1 for item in decisions if item.get("status") == "lost"),
        "win_rate_percent": round((wins / len(decisions) * 100.0) if decisions else 0.0, 4),
        "total_staked": round(total_staked, 2),
        "net_profit": round(profit, 2),
        "yield_percent": round(yield_pct, 4),
        "roi_percent": round(yield_pct, 4),
    }


def runtime_status() -> dict[str, Any]:
    adapters = list_adapters()
    with _LOCK:
        data = _load()
    return {
        "paper_mode": True,
        "live_execution_available": bool(adapters),
        "sportsbook_adapters": adapters,
        "plans": len(data["plans"]),
        "tracked_bets": len(data["bets"]),
        "executions": len(data["executions"]),
        "approval_required_for_live_bets": True,
    }
