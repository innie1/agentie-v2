import unittest
from pathlib import Path


class ApprovalCardRegressionTests(unittest.TestCase):
    def test_pending_approval_matches_original_agentie_approval_ui(self):
        text=Path("frontend/cards.js").read_text(encoding="utf-8")
        self.assertIn("className='browser-approval-step'",text)
        self.assertIn("className='browser-approval-actions'",text)
        self.assertIn("approve.className='approve'",text)
        self.assertIn("approve.textContent='Approve once'",text)
        self.assertIn("deny.textContent='Deny'",text)
        self.assertIn(".browser-approval-actions .approve{background:var(--accent);color:var(--accent-text);border-color:var(--accent)}",text)
        self.assertIn("/approvals/${encodeURIComponent(i.id)}/resolve",text)
        self.assertIn("body:JSON.stringify({approved})",text)


if __name__ == "__main__":
    unittest.main()
