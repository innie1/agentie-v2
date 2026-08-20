import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from agentie.core import reference_router
from agentie.tools import local_utility_tools as local_utils


class LocalConversationAndTimerRegressionTests(unittest.TestCase):
    def tearDown(self):
        with local_utils._TIMER_LOCK:
            local_utils._TIMERS.clear()

    def test_basic_greetings_are_handled_locally(self):
        for message in ("hi", "hello", "hey", "hiya", "helllo", "what's up", "thanks"):
            with self.subTest(message=message):
                result = reference_router.try_active_reference("test:chat", message)
                self.assertIsNotNone(result)
                self.assertEqual(result.get("routed_by"), "local_conversation")
                self.assertTrue(result.get("message"))

    def test_real_work_is_not_mistaken_for_smalltalk(self):
        self.assertIsNone(reference_router._local_smalltalk("build a website for my company"))
        self.assertIsNone(reference_router._local_smalltalk("research competitors and write a report"))

    def test_add_ten_seconds_uses_active_timer_without_repeating_timer_word(self):
        item = local_utils._create_timer(20, "Timer", "timer")
        card = {
            "type": "timer",
            "id": item["id"],
            "status": "running",
            "duration_seconds": 20,
            "due_at": (datetime.now() + timedelta(seconds=5)).isoformat(timespec="milliseconds"),
        }
        active = {"type": "timer", "card": card}
        with patch.object(reference_router, "get_context", return_value=active), patch.object(reference_router, "set_context"):
            result = reference_router.try_active_reference("test:timer", "add 10s")
        self.assertIsNotNone(result)
        self.assertEqual(result.get("routed_by"), "active_reference")
        self.assertIn("extended", result.get("message", "").lower())
        remaining = float(result["card"]["duration_seconds"])
        self.assertGreaterEqual(remaining, 14.0)
        self.assertLessEqual(remaining, 16.0)

    def test_timer_extension_does_not_add_to_original_duration(self):
        item = local_utils._create_timer(20, "Timer", "timer")
        card = {
            "type": "timer",
            "id": item["id"],
            "status": "running",
            "duration_seconds": 20,
            "due_at": (datetime.now() + timedelta(seconds=3)).isoformat(timespec="milliseconds"),
        }
        active = {"type": "timer", "card": card}
        with patch.object(reference_router, "get_context", return_value=active), patch.object(reference_router, "set_context"):
            result = reference_router.try_active_reference("test:timer", "extend it by 10 seconds")
        remaining = float(result["card"]["duration_seconds"])
        self.assertLess(remaining, 15.0, "Timer extension must use remaining time, not original 20 seconds.")

    def test_smalltalk_router_has_no_provider_dependency(self):
        text = open("agentie/core/reference_router.py", encoding="utf-8").read()
        block = text[text.index("_SMALLTALK="):text.index("def _direct_role_command")]
        self.assertNotIn("run_agent(", block)
        self.assertNotIn("provider", block.lower())


if __name__ == "__main__":
    unittest.main()
