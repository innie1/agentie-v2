import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.tools import approval_tools


class CompanyComputerApprovalExecutionRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Path(self.temp.name) / "approvals.json"
        self.patch = patch.object(approval_tools, "STORE", self.store)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_approved_guest_command_executes_once_and_is_consumed(self):
        item = approval_tools.create_approval(
            "computer:guest:apt-get install -y inkscape",
            "Install software",
            {
                "kind": "computer_guest_command",
                "command": "apt-get install -y inkscape",
                "agent_id": "agt_ops",
                "persistent_change": True,
            },
        )
        result = {"message": "Company Computer terminal command completed.", "terminal": {"exit_code": 0}}
        with patch("agentie.core.company_computer_commands.execute_approved_guest_command", return_value=result) as execute:
            resolved = approval_tools.resolve_approval(item["id"], True)
        execute.assert_called_once_with("apt-get install -y inkscape", "agt_ops")
        self.assertEqual(resolved["status"], "consumed")
        self.assertEqual(resolved["execution_result"]["terminal"]["exit_code"], 0)
        stored = approval_tools.get_approval(item["id"])
        self.assertEqual(stored["status"], "consumed")
        self.assertIsNotNone(stored.get("consumed_at"))

    def test_denied_guest_command_never_executes(self):
        item = approval_tools.create_approval(
            "computer:guest:rm -rf /home/agentie/old",
            "Delete files",
            {"kind": "computer_guest_command", "command": "rm -rf /home/agentie/old", "agent_id": "agt_ops"},
        )
        with patch("agentie.core.company_computer_commands.execute_approved_guest_command") as execute:
            resolved = approval_tools.resolve_approval(item["id"], False)
        execute.assert_not_called()
        self.assertEqual(resolved["status"], "denied")


if __name__ == "__main__":
    unittest.main()
