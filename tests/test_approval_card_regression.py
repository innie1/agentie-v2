import unittest
from pathlib import Path


class ApprovalCardRegressionTests(unittest.TestCase):
    def test_pending_approval_renders_approve_and_deny_buttons(self):
        text=Path("frontend/cards.js").read_text(encoding="utf-8")
        self.assertIn("approve.textContent='Approve'",text)
        self.assertIn("deny.textContent='Deny'",text)
        self.assertIn("/approvals/${encodeURIComponent(i.id)}/resolve",text)
        self.assertIn("body:JSON.stringify({approved})",text)


if __name__ == "__main__":
    unittest.main()
