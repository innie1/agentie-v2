import unittest

from agentie.core.browser_automation import _CONSEQUENTIAL, _click_target, _is_interactive_request, _steps, _type_parts
from agentie.core.browser_monitor import _looks_browser_request


class BrowserAutomationRegressionTests(unittest.TestCase):
    def test_screenshot_request_stays_on_capture_path(self):
        text = "Take a screenshot of https://example.com"
        self.assertTrue(_looks_browser_request(text))
        self.assertFalse(_is_interactive_request(text))

    def test_url_plus_click_uses_persistent_browser(self):
        self.assertTrue(_is_interactive_request("Open https://example.com and then click Learn more"))

    def test_followup_click_needs_no_url(self):
        self.assertTrue(_is_interactive_request("Click Learn more"))
        self.assertTrue(_is_interactive_request("Scroll down"))
        self.assertTrue(_is_interactive_request("Go back"))

    def test_multistep_parser_keeps_order(self):
        text = "Open https://example.com then scroll down then click Learn more"
        self.assertEqual(_steps(text, "https://example.com"), ["scroll down", "click Learn more"])
        self.assertEqual(_click_target("click Learn more"), "Learn more")

    def test_type_parser(self):
        self.assertEqual(_type_parts('Type "hello world" into Search'), ("hello world", "Search"))
        self.assertEqual(_type_parts('Fill Email with "user@example.com"'), ("user@example.com", "Email"))

    def test_consequential_actions_are_detected(self):
        for text in ("click Buy now", "submit the form", "delete account", "pay now", "send message"):
            with self.subTest(text=text):
                self.assertIsNotNone(_CONSEQUENTIAL.search(text))
        self.assertIsNone(_CONSEQUENTIAL.search("click Learn more"))


if __name__ == "__main__":
    unittest.main()
