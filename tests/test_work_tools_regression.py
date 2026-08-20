import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.tools import registry, work_tools


class WorkToolsRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.contacts = root / "contacts.json"
        self.monitors = root / "website_monitors.json"
        self.calendar = root / "calendar_events.json"
        self.patches = [
            patch.object(work_tools, "CONTACTS_FILE", self.contacts),
            patch.object(work_tools, "MONITORS_FILE", self.monitors),
            patch.object(work_tools, "CALENDAR_FILE", self.calendar),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_existing_core_tools_are_still_registered(self):
        names = {getattr(tool, "name", "") for tool in registry.tools_for("general")}
        for expected in ("calculate", "search_web", "read_text_file", "run_python", "remember", "create_task"):
            self.assertIn(expected, names)

    def test_new_tools_are_additive(self):
        names = {getattr(tool, "name", "") for tool in registry.tools_for("general")}
        for expected in ("plan_task", "save_contact", "find_contacts", "create_calendar_event", "list_calendar_events", "create_website_monitor", "list_website_monitors"):
            self.assertIn(expected, names)

    def test_contact_store_round_trip_helpers(self):
        work_tools._save(self.contacts, [{"id": "1", "name": "Ada", "email": "ada@example.com", "phone": "", "company": "INNIE", "notes": "supplier"}])
        rows = work_tools._load(self.contacts, [])
        self.assertEqual(rows[0]["name"], "Ada")
        self.assertEqual(rows[0]["company"], "INNIE")

    def test_monitor_store_is_isolated_and_persistent(self):
        item = {"id": "abc", "url": "https://example.com", "label": "Example", "check_for": "changes", "status": "active"}
        work_tools._save(self.monitors, [item])
        self.assertEqual(work_tools._load(self.monitors, [])[0]["url"], "https://example.com")

    def test_calendar_store_is_isolated_and_persistent(self):
        item = {"id": "event1", "title": "Supplier call", "start": "2026-08-21T10:00", "status": "scheduled"}
        work_tools._save(self.calendar, [item])
        self.assertEqual(work_tools._load(self.calendar, [])[0]["title"], "Supplier call")


if __name__ == "__main__":
    unittest.main()
