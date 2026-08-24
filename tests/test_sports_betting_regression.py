import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import skill_registry
from agentie.core import sports_betting as betting
from agentie.core.sports_betting_skill import route_sports_betting_command
from agentie.core.sportybet_adapter import SportyBetAdapter, _event_teams
from agentie.core.sportsbook_adapters import SportsbookAdapter, get_adapter, register_adapter, unregister_adapter
from agentie.tools import approval_tools


class FakeSportsbook(SportsbookAdapter):
    def __init__(self, sportsbook_id, *, changed_odds=None, fail_submit=False):
        self.sportsbook_id = sportsbook_id
        self.display_name = sportsbook_id.title()
        self.changed_odds = changed_odds
        self.fail_submit = fail_submit
        self.prepared_count = 0
        self.rechecked_count = 0
        self.submitted_count = 0
        self.abandoned_count = 0

    async def prepare_bet(self, leg):
        self.prepared_count += 1
        return {"sportsbook": self.sportsbook_id, "leg": dict(leg), "token": f"{self.sportsbook_id}-slip"}

    async def recheck_bet(self, prepared):
        self.rechecked_count += 1
        leg = prepared["leg"]
        return {
            "available": True,
            "odds": self.changed_odds if self.changed_odds is not None else leg["odds"],
            "max_stake": leg["stake"] + 1000,
        }

    async def submit_bet(self, prepared):
        self.submitted_count += 1
        if self.fail_submit:
            raise RuntimeError("book rejected bet")
        return {"accepted": True, "reference": f"{self.sportsbook_id}-123"}

    async def abandon_prepared_bet(self, prepared):
        self.abandoned_count += 1


class SportsBettingRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.state = root / "sports_betting.json"
        self.approvals = root / "approvals.json"
        self.state_patch = patch.object(betting, "STATE", self.state)
        self.approval_patch = patch.object(approval_tools, "STORE", self.approvals)
        self.state_patch.start()
        self.approval_patch.start()
        for sid in ("booka", "bookb", "missing"):
            unregister_adapter(sid)
        if get_adapter("sportybet") is None:
            register_adapter(SportyBetAdapter())

    def tearDown(self):
        for sid in ("booka", "bookb", "missing"):
            unregister_adapter(sid)
        self.approval_patch.stop()
        self.state_patch.stop()
        self.temp.cleanup()

    def _arb_legs(self):
        return [
            {"sportsbook": "booka", "event": "A v B", "market": "Winner", "selection": "A", "odds": 2.10},
            {"sportsbook": "bookb", "event": "A v B", "market": "Winner", "selection": "B", "odds": 2.10},
        ]

    def test_arbitrage_engine_splits_stakes_for_equal_payout(self):
        result = betting.detect_arbitrage(self._arb_legs(), 100000)
        self.assertTrue(result["arbitrage"])
        self.assertGreater(result["expected_profit"], 0)
        payouts = [leg["target_payout"] for leg in result["legs"]]
        self.assertAlmostEqual(payouts[0], payouts[1], places=2)
        self.assertAlmostEqual(sum(leg["stake"] for leg in result["legs"]), 100000, places=2)

    def test_non_arbitrage_is_not_presented_as_guaranteed_profit(self):
        legs = [
            {"event": "A v B", "market": "Winner", "selection": "A", "odds": 1.80},
            {"event": "A v B", "market": "Winner", "selection": "B", "odds": 1.80},
        ]
        result = betting.detect_arbitrage(legs, 50000)
        self.assertFalse(result["arbitrage"])
        self.assertEqual(result["expected_profit"], 0)

    def test_value_engine_reports_ev_and_caps_fractional_kelly_stake(self):
        result = betting.analyze_value_bet(odds=2.2, true_probability=0.55, bankroll=100000)
        self.assertTrue(result["positive_ev"])
        self.assertGreater(result["expected_value_percent"], 0)
        self.assertLessEqual(result["recommended_stake"], 2000.0)

    def test_paper_bets_are_persistent_and_monthly_performance_is_calculated(self):
        first = betting.record_bet(strategy="value", sportsbook="paper", event="A v B", market="Winner", selection="A", odds=2.0, stake=1000)
        second = betting.record_bet(strategy="value", sportsbook="paper", event="C v D", market="Winner", selection="D", odds=2.0, stake=1000)
        betting.settle_bet(first["id"], outcome="won")
        betting.settle_bet(second["id"], outcome="lost")
        month = first["placed_at"][:7]
        result = betting.performance(month=month, mode="paper")
        self.assertEqual(result["settled"], 2)
        self.assertEqual(result["wins"], 1)
        self.assertEqual(result["losses"], 1)
        self.assertEqual(result["total_staked"], 2000.0)
        self.assertEqual(result["net_profit"], 0.0)

    def test_live_plan_refuses_missing_adapter_instead_of_simulating_site(self):
        plan = betting.create_execution_plan(
            strategy="arbitrage",
            legs=[{"sportsbook": "missing", "event": "A v B", "market": "Winner", "selection": "A", "odds": 2.1, "stake": 1000}],
        )
        with self.assertRaises(RuntimeError) as ctx:
            betting.prepare_execution_plan(plan["id"])
        message = str(ctx.exception).lower()
        self.assertIn("unavailable", message)
        self.assertIn("adapter", message)
        self.assertIn("missing", message)

    def test_changed_leg_aborts_every_site_before_any_submit(self):
        booka = FakeSportsbook("booka")
        bookb = FakeSportsbook("bookb", changed_odds=2.05)
        register_adapter(booka)
        register_adapter(bookb)
        arb = betting.detect_arbitrage(self._arb_legs(), 10000)
        plan = betting.create_execution_plan(strategy="arbitrage", legs=arb["legs"], expected_profit=arb["expected_profit"])
        approval = betting.request_execution_approval(plan["id"])
        resolved = approval_tools.resolve_approval(approval["id"], True)
        result = resolved["execution_result"]
        self.assertEqual(result["status"], "changed")
        self.assertFalse(result["submitted"])
        self.assertEqual(booka.submitted_count, 0)
        self.assertEqual(bookb.submitted_count, 0)
        self.assertEqual(booka.abandoned_count, 1)
        self.assertEqual(bookb.abandoned_count, 1)
        self.assertTrue(any(item["sportsbook"] == "bookb" for item in result["changes"]))

    def test_accept_executes_exact_unchanged_plan_once(self):
        booka = FakeSportsbook("booka")
        bookb = FakeSportsbook("bookb")
        register_adapter(booka)
        register_adapter(bookb)
        arb = betting.detect_arbitrage(self._arb_legs(), 10000)
        plan = betting.create_execution_plan(strategy="arbitrage", legs=arb["legs"], expected_profit=arb["expected_profit"])
        approval = betting.request_execution_approval(plan["id"])
        resolved = approval_tools.resolve_approval(approval["id"], True)
        self.assertEqual(resolved["status"], "consumed")
        self.assertEqual(resolved["execution_result"]["status"], "submitted")
        self.assertEqual(booka.submitted_count, 1)
        self.assertEqual(bookb.submitted_count, 1)
        with self.assertRaises(ValueError):
            approval_tools.resolve_approval(approval["id"], True)

    def test_builtin_skill_registers_real_sportybet_adapter(self):
        item = skill_registry.all_skills()["sports-betting"]
        self.assertTrue(item["enabled"])
        self.assertIn("arbitrage", item["capabilities"])
        self.assertTrue(item["runtime"]["paper_mode"])
        self.assertTrue(item["runtime"]["live_execution_available"])
        adapter_ids = {row["id"] for row in item["runtime"]["sportsbook_adapters"]}
        self.assertIn("sportybet", adapter_ids)
        self.assertIsInstance(get_adapter("sportybet"), SportyBetAdapter)

    def test_sportybet_event_parser_handles_common_match_names(self):
        self.assertEqual(_event_teams("Arsenal v Chelsea"), ["Arsenal", "Chelsea"])
        self.assertEqual(_event_teams("Arsenal vs Chelsea"), ["Arsenal", "Chelsea"])
        self.assertEqual(_event_teams("Arsenal - Chelsea"), ["Arsenal", "Chelsea"])

    def test_sportybet_status_exposes_safe_browser_policy(self):
        item = skill_registry.all_skills()["sports-betting"]
        sporty = next(row for row in item["runtime"]["sportsbook_adapters"] if row["id"] == "sportybet")
        diag = sporty["diagnostics"]
        self.assertEqual(diag["browser_mode"], "persistent_visible_chromium")
        self.assertTrue(diag["human_takeover"])
        self.assertTrue(diag["approval_required"])
        self.assertTrue(diag["recheck_before_submit"])
        self.assertFalse(diag["automatic_submit_retry"])
        self.assertFalse(diag["anti_bot_evasion"])

    def test_sportybet_adapter_does_not_add_stealth_or_proxy_bypass_code(self):
        source = Path("agentie/core/sportybet_adapter.py").read_text(encoding="utf-8").lower()
        forbidden = (
            "playwright_stealth",
            "navigator.webdriver",
            "automationcontrolled",
            "residential_proxy",
            "proxy_server=",
        )
        for marker in forbidden:
            self.assertNotIn(marker, source)

    def test_skill_routes_manual_arbitrage_and_value_analysis(self):
        arb = route_sports_betting_command("calculate arbitrage odds 2.10, 2.10 bankroll 10000")
        self.assertIsNotNone(arb)
        self.assertTrue(arb["card"]["arbitrage"])
        value = route_sports_betting_command("calculate value bet odds 2.20 probability 55% bankroll 100000")
        self.assertIsNotNone(value)
        self.assertTrue(value["card"]["positive_ev"])

    def test_multiline_betting_commands_do_not_fall_through_to_calculator(self):
        result = route_sports_betting_command(
            "sports betting status\n"
            "calculate arbitrage odds 2.10, 2.10 bankroll 10000\n"
            "calculate value bet odds 2.20 probability 55% bankroll 100000\n"
            "show betting performance"
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["card"]["type"], "sports_betting_batch")
        self.assertEqual(len(result["card"]["items"]), 4)
        self.assertEqual(result["card"]["items"][0]["type"], "sports_betting_status")
        self.assertEqual(result["card"]["items"][1]["type"], "arbitrage_analysis")
        self.assertEqual(result["card"]["items"][2]["type"], "value_bet_analysis")
        self.assertEqual(result["card"]["items"][3]["type"], "sports_betting_performance")


if __name__ == "__main__":
    unittest.main()
