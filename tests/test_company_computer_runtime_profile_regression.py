import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import company_computer_runtime_profile as profile


class CompanyComputerRuntimeProfileRegressionTests(unittest.TestCase):
    def test_stale_live_runtime_relaunches_without_touching_persistent_disk(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / "runtime-profile.version"
            disk = Path(temp) / "company-computer.qcow2"
            disk.write_bytes(b"persistent-files-cookies-apps")
            row = {"state": "IDLE", "vm_pid": 123}
            started = {"state": "READY", "vm_pid": 456}

            with patch.object(profile, "_PROFILE_FILE", marker), \
                 patch.object(profile.computer, "DISK", disk), \
                 patch.object(profile.computer, "_row", return_value=row), \
                 patch.object(profile.computer, "_is_pid_alive", return_value=True), \
                 patch.object(profile.computer, "stop") as stop, \
                 patch.object(profile, "_ORIGINAL_START", return_value=started) as original_start:
                result = profile.start()

            stop.assert_called_once()
            original_start.assert_called_once()
            self.assertEqual(result, started)
            self.assertEqual(disk.read_bytes(), b"persistent-files-cookies-apps")
            self.assertEqual(marker.read_text(encoding="utf-8").strip(), profile._PROFILE_VERSION)

    def test_stale_live_runtime_relaunches_even_when_vnc_never_opened(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / "runtime-profile.version"
            row = {"state": "STARTING", "vm_pid": 123}
            with patch.object(profile, "_PROFILE_FILE", marker), \
                 patch.object(profile.computer, "_row", return_value=row), \
                 patch.object(profile.computer, "_is_pid_alive", return_value=True), \
                 patch.object(profile.computer, "_port_open", return_value=False) as port_open, \
                 patch.object(profile.computer, "stop") as stop, \
                 patch.object(profile, "_ORIGINAL_START", return_value={"state": "READY"}):
                profile.start()
            stop.assert_called_once()
            port_open.assert_not_called()

    def test_current_runtime_profile_reuses_live_vm_without_relaunch(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / "runtime-profile.version"
            marker.write_text(profile._PROFILE_VERSION + "\n", encoding="utf-8")
            row = {"state": "IDLE", "vm_pid": 123}
            started = {"state": "IDLE", "vm_pid": 123}

            with patch.object(profile, "_PROFILE_FILE", marker), \
                 patch.object(profile.computer, "_row", return_value=row), \
                 patch.object(profile.computer, "_is_pid_alive", return_value=True), \
                 patch.object(profile.computer, "stop") as stop, \
                 patch.object(profile, "_ORIGINAL_START", return_value=started):
                result = profile.start()

            stop.assert_not_called()
            self.assertEqual(result, started)

    def test_suspended_stale_runtime_is_resumed_before_graceful_stop(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / "runtime-profile.version"
            row = {"state": "SUSPENDED", "vm_pid": 123}
            calls = []

            def qmp(command, *args, **kwargs):
                calls.append(command)
                return {"return": {}}

            with patch.object(profile, "_PROFILE_FILE", marker), \
                 patch.object(profile.computer, "_row", return_value=row), \
                 patch.object(profile.computer, "_is_pid_alive", return_value=True), \
                 patch.object(profile.computer, "_qmp_command", side_effect=qmp), \
                 patch.object(profile.computer, "_update"), \
                 patch.object(profile.computer, "stop") as stop, \
                 patch.object(profile, "_ORIGINAL_START", return_value={"state": "READY"}):
                profile.start()

            self.assertIn("cont", calls)
            stop.assert_called_once()

    def test_controlled_runtime_is_not_restarted_under_user_or_agent(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / "runtime-profile.version"
            for state in ("USER_CONTROL", "AGENT_CONTROL", "USER_REQUIRED"):
                row = {"state": state, "vm_pid": 123}
                with patch.object(profile, "_PROFILE_FILE", marker), \
                     patch.object(profile.computer, "_row", return_value=row), \
                     patch.object(profile.computer, "_is_pid_alive", return_value=True):
                    with self.assertRaises(profile.computer.ComputerError):
                        profile.start()


if __name__ == "__main__":
    unittest.main()
