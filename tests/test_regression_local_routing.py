import unittest

from agentie.core.code_execution import route_code_command
from agentie.core.local_router import route_local_actions
from agentie.core.reference_router import _direct_timer_create


class StableTimerIntentTests(unittest.TestCase):
    def assert_timer(self, text: str, seconds: float) -> None:
        result = _direct_timer_create(text)
        self.assertIsNotNone(result, text)
        self.assertIsInstance(result.get("card"), dict)
        self.assertEqual(result["card"].get("type"), "timer")
        self.assertEqual(float(result["card"].get("duration_seconds")), seconds)

    def test_timer_shorthand_variants(self):
        for text in (
            "timer 10s",
            "timer 10 s",
            "timer for 10 s",
            "a timer for 10 s",
            "set a timer for 10 seconds",
            "start timer 10 sec",
        ):
            with self.subTest(text=text):
                self.assert_timer(text, 10.0)

    def test_timer_reason(self):
        result = _direct_timer_create("timer 20s to check the build")
        self.assertEqual(result["card"].get("reason"), "check the build")


class ExistingLocalBehaviorTests(unittest.TestCase):
    def test_calculation_still_local(self):
        routed = route_local_actions("Calculate 321 * 27")
        self.assertFalse(routed["unresolved"])
        self.assertEqual(routed["results"][0]["card"]["type"], "calculation")
        self.assertEqual(routed["results"][0]["card"]["result"], 8667)

    def test_conversion_still_local(self):
        routed = route_local_actions("Convert 12 kilometers to miles")
        self.assertFalse(routed["unresolved"])
        self.assertIn(routed["results"][0]["card"]["type"], {"conversion", "unit_conversion"})

    def test_time_still_local(self):
        routed = route_local_actions("What time is it")
        self.assertFalse(routed["unresolved"])
        self.assertEqual(routed["results"][0]["card"]["type"], "datetime")

    def test_one_line_python_never_needs_model(self):
        result = route_code_command("Run Python: print(sum(i * i for i in range(1, 101)))")
        self.assertIsNotNone(result)
        self.assertEqual(result["card"]["type"], "multi")
        first = result["card"]["items"][0]["card"]
        self.assertEqual(first["type"], "note")
        self.assertIn("338350", first["content"])


if __name__ == "__main__":
    unittest.main()
