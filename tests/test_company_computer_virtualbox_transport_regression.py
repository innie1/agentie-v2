from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import company_computer_virtualbox as vbox
from agentie.core import company_computer_virtualbox_guestcontrol as guestcontrol
from agentie.core import company_computer_virtualbox_recovery as recovery


class CompanyComputerVirtualBoxTransportRegressionTests(unittest.TestCase):
    def test_guestcontrol_passes_only_command_arguments_after_separator(self):
        captured: list[str] = []

        def fake_run(args, **kwargs):
            captured.extend(args)
            return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(vbox, "ROOT", Path(tmp)),
                patch.object(vbox, "guest_credentials", return_value=("agentie", "secret")),
                patch.object(vbox, "_run", side_effect=fake_run),
            ):
                result = guestcontrol.guest_exec(["/bin/bash", "-lc", "echo hello"], timeout=5)
        self.assertEqual(result["exitcode"], 0)
        self.assertIn("--exe", captured)
        exe_index = captured.index("--exe")
        self.assertEqual(captured[exe_index + 1], "/bin/bash")
        separator = captured.index("--")
        self.assertEqual(captured[separator + 1 :], ["-lc", "echo hello"])
        self.assertNotEqual(captured[separator + 1], "/bin/bash")

    def test_failed_new_disk_attempt_removes_only_partial_vdi(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            disk = root / "company-computer.vdi"

            def fail(_profile=None):
                disk.write_bytes(b"partial")
                raise vbox.ComputerError("conversion failed")

            with patch.object(vbox, "DISK", disk), patch.object(recovery, "_ORIGINAL_ENSURE_DISK", side_effect=fail):
                with self.assertRaises(vbox.ComputerError):
                    recovery.ensure_disk({"system": "windows"})
            self.assertFalse(disk.exists())

    def test_failed_attempt_never_deletes_existing_vdi(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            disk = root / "company-computer.vdi"
            disk.write_bytes(b"existing-user-data")
            with patch.object(vbox, "DISK", disk), patch.object(recovery, "_ORIGINAL_ENSURE_DISK", side_effect=vbox.ComputerError("failed")):
                with self.assertRaises(vbox.ComputerError):
                    recovery.ensure_disk({"system": "windows"})
            self.assertEqual(disk.read_bytes(), b"existing-user-data")

    def test_failed_fresh_vm_is_unregistered_without_delete(self):
        calls: list[list[str]] = []

        def fake_run(args, **kwargs):
            calls.append(list(args))
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        with (
            patch.object(recovery, "_ORIGINAL_CREATE_VM", side_effect=vbox.ComputerError("attach failed")),
            patch.object(vbox, "_vm_exists", side_effect=[False, True]),
            patch.object(vbox, "_run", side_effect=fake_run),
        ):
            with self.assertRaises(vbox.ComputerError):
                recovery._create_vm({"vm_ram_mb": 1024, "vm_vcpus": 1})
        self.assertTrue(calls)
        self.assertEqual(calls[-1], ["unregistervm", vbox.VM_NAME])
        self.assertNotIn("--delete", calls[-1])


if __name__ == "__main__":
    unittest.main()
