from __future__ import annotations

import re
from typing import Any

from agentie.core.sports_betting import analyze_value_bet, detect_arbitrage, performance, runtime_status


def _money(text: str) -> float:
    return float(str(text).replace(",", "").strip())


def _odds_list(text: str) -> list[float]:
    values = [part.strip() for part in re.split(r"[,;/ ]+", str(text or "")) if part.strip()]
    return [float(value) for value in values]


def route_sports_betting_command(message: str) -> dict[str, Any] | None:
    text = " ".join(str(message or "").strip().split())
    lower = text.casefold().strip(" .?!")

    if lower in {
        "sports betting status",
        "betting status",
        "show sports betting",
        "show betting status",
        "show sportsbook adapters",
        "sportsbook adapters",
    }:
        status = runtime_status()
        if status["sportsbook_adapters"]:
            message_text = f"Sports Betting is ready with {len(status['sportsbook_adapters'])} live sportsbook adapter(s)."
        else:
            message_text = "Sports Betting paper analysis is ready. Live betting stays disabled until a real sportsbook adapter is installed and tested."
        return {"message": message_text, "card": {"type": "sports_betting_status", **status}}

    match = re.match(
        r"^(?:calculate|check|analyze)\s+(?:an\s+)?arbitrage(?:\s+for)?\s+odds\s+(.+?)\s+(?:with\s+)?bankroll\s+([0-9][0-9,]*(?:\.\d+)?)$",
        text,
        re.I,
    )
    if match:
        try:
            odds = _odds_list(match.group(1))
            bankroll = _money(match.group(2))
            legs = [
                {"event": "Manual arbitrage check", "market": "Manual market", "selection": f"Outcome {index + 1}", "odds": price}
                for index, price in enumerate(odds)
            ]
            result = detect_arbitrage(legs, bankroll)
        except ValueError as exc:
            return {"message": str(exc), "card": None}
        message_text = (
            f"Arbitrage found: expected profit {result['expected_profit']:.2f} ({result['expected_profit_percent']:.2f}%)."
            if result["arbitrage"]
            else "Those odds do not currently form an arbitrage."
        )
        return {"message": message_text, "card": result}

    match = re.match(
        r"^(?:calculate|check|analyze)\s+(?:a\s+)?(?:value bet|\+ev bet|ev bet)(?:\s+for)?\s+odds\s+([0-9]+(?:\.\d+)?)\s+(?:with\s+)?(?:true\s+)?probability\s+([0-9]+(?:\.\d+)?)%?\s+(?:and\s+|with\s+)?bankroll\s+([0-9][0-9,]*(?:\.\d+)?)$",
        text,
        re.I,
    )
    if match:
        try:
            probability = float(match.group(2))
            if probability > 1:
                probability /= 100.0
            result = analyze_value_bet(
                odds=float(match.group(1)),
                true_probability=probability,
                bankroll=_money(match.group(3)),
            )
        except ValueError as exc:
            return {"message": str(exc), "card": None}
        message_text = (
            f"This is +EV by {result['expected_value_percent']:.2f}% per unit at the supplied probability estimate."
            if result["positive_ev"]
            else "This is not a +EV bet at the supplied probability estimate."
        )
        return {"message": message_text, "card": result}

    match = re.match(
        r"^(?:show|check|view)\s+(?:my\s+)?(?:sports\s+)?betting\s+(?:performance|results)(?:\s+for\s+(\d{4}-\d{2}))?(?:\s+(paper|real))?$",
        text,
        re.I,
    )
    if match:
        try:
            result = performance(month=match.group(1), mode=match.group(2))
        except ValueError as exc:
            return {"message": str(exc), "card": None}
        return {
            "message": f"Betting performance: {result['net_profit']:.2f} net, {result['yield_percent']:.2f}% yield across {result['settled']} settled bet(s).",
            "card": result,
        }

    return None
