import unittest
from unittest.mock import patch

from agentie.core import company_computer as cc
from agentie.core import company_computer_resume_compat as compat


class CompanyComputerResumeRegressionTests(unittest.TestCase):
    def test_start_resumes_live_suspended_vm_before_returning(self):
        suspended = {"state": "SUSPENDED", "vm_pid": 4242}
        resumed = {"state": "IDLE", "vm_pid": 4242}
        with patch.object(cc, "_row", return_value=suspended), \
             patch.object(cc, "_is_pid_alive", return_value=True), \
             patch.object(cc, "_qmp_command", return_value={"return": {}}) as qmp, \
             patch.object(cc, "_update", return_value=resumed) as update, \
             patch.object(cc, "_start_display_server") as display, \
             patch.object(cc, "start_idle_monitor") as idle, \
             patch.object(cc, "status", return_value=resumed):
            result = compat.start()

        qmp.assert_called_once_with("cont")
        update.assert_called_once()
        self.assertEqual(update.call_args.kwargs["state"], "IDLE")
        self.assertEqual(update.call_args.kwargs["suspended_snapshot"], 0)
        display.assert_called_once()
        idle.assert_called_once()
        self.assertEqual(result["state"], "IDLE")

    def test_start_delegates_normally_when_vm_is_not_suspended(self):
        with patch.object(cc, "_row", return_value={"state": "READY", "vm_pid": 4242}), \
             patch.object(compat, "_ORIGINAL_START", return_value={"state": "READY"}) as original:
            result = compat.start()
        original.assert_called_once_with()
        self.assertEqual(result["state"], "READY")

    def test_resume_failure_is_actionable_and_does_not_fake_running_state(self):
        with patch.object(cc, "_row", return_value={"state": "SUSPENDED", "vm_pid": 4242}), \
             patch.object(cc, "_is_pid_alive", return_value=True), \
             patch.object(cc, "_qmp_command", side_effect=OSError("QMP unavailable")), \
             patch.object(cc, "_update") as update:
            with self.assertRaises(cc.ComputerError) as ctx:
                compat.start()
        update.assert_not_called()
        self.assertIn("Could not resume suspended Agentie Computer", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
