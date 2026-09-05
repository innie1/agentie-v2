import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import company_computer as computer
from agentie.core import company_computer_backend as backend


class CompanyComputerSingleRuntimeRegressionTests(unittest.TestCase):
    def test_user_takeover_and_return_include_live_display_status(self):
        for action in ("acquire_user", "continue_agent"):
            with self.subTest(action=action), patch.object(backend, "_call") as call:
                call.side_effect = [{"state": "USER_CONTROL"}, {"state": "USER_CONTROL", "running": True, "display_ready": True, "display_url": "http://localhost:6088/vnc.html"}]
                result = getattr(backend, action)()
                self.assertTrue(result["display_ready"])
                self.assertTrue(result["running"])
                self.assertIn("vnc.html", result["display_url"])
                self.assertEqual(call.call_args_list[-1].args, ("status",))

    def test_qemu_is_the_only_backend_on_every_host(self):
        with patch.dict(os.environ, {"AGENTIE_COMPUTER_BACKEND": ""}):
            for system in ("Windows", "Darwin", "Linux"):
                self.assertEqual(backend.backend_name(system), "qemu")
        with patch.dict(os.environ, {"AGENTIE_COMPUTER_BACKEND": "virtualbox"}):
            with self.assertRaises(computer.ComputerError):
                backend.backend_name("Windows")

    def test_generic_debian_and_persistent_qcow2_are_distinct(self):
        self.assertEqual(computer._debian_filename({"machine": "x86_64"}), "debian-13-generic-amd64.qcow2")
        self.assertNotIn("genericcloud", computer._debian_url({"machine": "x86_64"}))
        self.assertEqual(computer.DISK.name, "company-computer.qcow2")
        self.assertNotEqual(computer.BASE_IMAGE, computer.DISK)

    def test_startup_timeout_is_configurable_for_slow_hosts(self):
        source = Path(computer.__file__).read_text(encoding="utf-8")
        self.assertIn("AGENTIE_QEMU_START_TIMEOUT_SECONDS", source)
        self.assertIn("if not vnc_ready", source)
        self.assertIn("ipv6=off", source)

    def test_control_takeover_resume_and_idle_state_keep_disk(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            disk = root / "company-computer.qcow2"
            disk.write_bytes(b"cookies-files-apps-settings")
            state = {
                "state": "IDLE", "controller_type": None, "controller_agent_id": None,
                "job_id": None, "takeover_reason": None, "control_generation": 0,
                "last_activity": 1.0, "vm_pid": 4242, "suspended_snapshot": 0,
            }

            def update(**values):
                state.update(values)
                return dict(state)

            with patch.object(computer, "DISK", disk), patch.object(computer, "start", return_value=dict(state)), patch.object(computer, "_row", side_effect=lambda: dict(state)), patch.object(computer, "_update", side_effect=update), patch.object(computer, "_now", return_value=10.0):
                acquired = computer.acquire_agent("agent-1")
                self.assertEqual(acquired["state"], "AGENT_CONTROL")
                requested = computer.request_user_takeover("agent-1", "Login required")
                self.assertEqual(requested["state"], "USER_REQUIRED")
                user = computer.acquire_user()
                self.assertEqual(user["state"], "USER_CONTROL")
                resumed = computer.continue_agent()
                self.assertEqual(resumed["state"], "AGENT_CONTROL")
                idle = computer.release_control("agent-1")
                self.assertEqual(idle["state"], "IDLE")

            self.assertEqual(disk.read_bytes(), b"cookies-files-apps-settings")

    def test_suspended_live_vm_resumes_in_place(self):
        suspended = {"state": "SUSPENDED", "vm_pid": 4242}
        resumed = {"state": "IDLE", "vm_pid": 4242}
        with patch.object(computer, "_row", return_value=suspended), patch.object(computer, "_is_pid_alive", return_value=True), patch.object(computer, "_qmp_command", return_value={"return": {}}) as qmp, patch.object(computer, "_update", return_value=resumed), patch.object(computer, "_start_display_server"), patch.object(computer, "start_idle_monitor"), patch.object(computer, "status", return_value=resumed):
            self.assertEqual(computer.start(), resumed)
        qmp.assert_called_once_with("cont")

    def test_long_guest_commands_refresh_idle_activity(self):
        responses = [{"return": {"pid": 7}}, {"return": {"exited": True, "exitcode": 0}}]
        with patch.object(computer, "_qga_request", side_effect=responses), patch.object(computer, "touch_activity") as touch:
            result = computer.guest_exec(["/bin/true"], timeout=5)
        self.assertEqual(result["exitcode"], 0)
        self.assertGreaterEqual(touch.call_count, 2)


if __name__ == "__main__":
    unittest.main()
