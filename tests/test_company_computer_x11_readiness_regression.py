import unittest
from unittest.mock import patch

from agentie.core import company_computer_guest_setup as setup


class CompanyComputerX11ReadinessRegressionTests(unittest.TestCase):
    def test_repair_waits_for_real_x11_client_not_only_socket(self):
        script = setup._repair_script()
        self.assertIn("xdotool getdisplaygeometry", script)
        self.assertNotIn("[ -S /tmp/.X11-unix/X0 ] && break", script)
        self.assertIn("touch /var/lib/agentie/runtime-v6", script)

    def test_health_check_requires_live_x_display(self):
        command = " ".join(setup._desktop_health_command())
        self.assertIn("agentie-xorg.service", command)
        self.assertIn("agentie-desktop.service", command)
        self.assertIn("DISPLAY=:0 /usr/bin/xdotool getdisplaygeometry", command)

    def test_suspended_guest_is_resumed_before_qga_wait(self):
        suspended = {"state": "SUSPENDED"}
        ready = {"state": "IDLE", "computer_id": "company-default"}
        healthy = {"exited": True, "exitcode": 0}
        with patch.object(setup.computer, "status", side_effect=[suspended, ready]) as status, \
             patch.object(setup.computer, "resume", return_value=ready) as resume, \
             patch.object(setup.computer, "start") as start, \
             patch.object(setup, "_wait_for_qga") as wait_qga, \
             patch.object(setup, "_wait_for_cloud_init"), \
             patch.object(setup, "_marker_exists", return_value=True), \
             patch.object(setup.computer, "guest_exec", return_value=healthy), \
             patch.object(setup.computer, "touch_activity"):
            result = setup.ensure_guest_runtime()
        resume.assert_called_once()
        start.assert_not_called()
        wait_qga.assert_called_once()
        self.assertEqual(result["state"], "IDLE")
        self.assertEqual(status.call_count, 2)


if __name__ == "__main__":
    unittest.main()
