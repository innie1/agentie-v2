from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import company_computer_virtualbox as vbox
from agentie.core import company_computer_virtualbox_provisioning as provisioning


class CompanyComputerVirtualBoxMigrationRegressionTests(unittest.TestCase):
    def paths(self, root: Path):
        return (
            patch.object(vbox, "ROOT", root),
            patch.object(vbox, "DISK", root / "company-computer.vdi"),
            patch.object(vbox, "OLD_QCOW2", root / "company-computer.qcow2"),
            patch.object(vbox, "OLD_QCOW2_BACKUP", root / "company-computer.pre-virtualbox-backup.qcow2"),
        )

    def test_direct_conversion_never_creates_raw_temporary_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, destination = root / "source.qcow2", root / "temporary.vdi"
            source.write_bytes(b"qcow2")

            def run(args, **kwargs):
                self.assertEqual(args[0], "clonemedium")
                self.assertNotIn("raw", " ".join(map(str, args)).lower())
                destination.write_bytes(b"vdi")
                return subprocess.CompletedProcess(args, 0, "", "")

            with patch.object(vbox, "_run", side_effect=run):
                vbox._convert_qcow2_to_vdi(source, destination)
            self.assertFalse((root / "company-computer-migration.raw").exists())

    def test_verification_precedes_atomic_activation_and_preserves_qcow2(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / "company-computer.qcow2"
            backup = root / "company-computer.pre-virtualbox-backup.qcow2"
            old.write_bytes(b"user-data")
            backup.write_bytes(b"backup-data")
            events = []

            def convert(source, temporary):
                self.assertEqual(source, old)
                self.assertNotEqual(temporary, root / "company-computer.vdi")
                temporary.write_bytes(b"valid-vdi")
                events.append("converted")

            def verify(temporary):
                self.assertFalse((root / "company-computer.vdi").exists())
                self.assertEqual(temporary.read_bytes(), b"valid-vdi")
                events.append("verified")

            ok = subprocess.CompletedProcess([], 0, stdout="", stderr="")
            with self.paths(root)[0], self.paths(root)[1], self.paths(root)[2], self.paths(root)[3], patch.object(vbox, "_convert_qcow2_to_vdi", side_effect=convert), patch.object(vbox, "_verify_vdi", side_effect=verify), patch.object(vbox, "_run_checked", return_value=ok):
                result = provisioning.ensure_disk({"system": "windows", "machine": "amd64"})
            self.assertEqual(events, ["converted", "verified"])
            self.assertEqual(result.read_bytes(), b"valid-vdi")
            self.assertEqual(old.read_bytes(), b"user-data")
            self.assertEqual(backup.read_bytes(), b"backup-data")

    def test_failed_low_space_migration_cleans_only_temporary_vdi(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / "company-computer.qcow2"
            backup = root / "company-computer.pre-virtualbox-backup.qcow2"
            old.write_bytes(b"user-data")
            backup.write_bytes(b"backup-data")

            def fail(source, temporary):
                temporary.write_bytes(b"partial")
                raise OSError(28, "No space left on device")

            with self.paths(root)[0], self.paths(root)[1], self.paths(root)[2], self.paths(root)[3], patch.object(vbox, "_convert_qcow2_to_vdi", side_effect=fail):
                with self.assertRaises(vbox.ComputerError) as ctx:
                    provisioning.ensure_disk({"system": "windows", "machine": "amd64"})
            self.assertIn("disk space", str(ctx.exception).lower())
            self.assertIn("writable", str(ctx.exception).lower())
            self.assertEqual(old.read_bytes(), b"user-data")
            self.assertEqual(backup.read_bytes(), b"backup-data")
            self.assertFalse((root / "company-computer.vdi").exists())
            self.assertEqual(list(root.glob(".company-computer.vdi.*.tmp")), [])

    def test_failed_verification_does_not_activate_temporary_vdi(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "company-computer.qcow2").write_bytes(b"user-data")
            (root / "company-computer.pre-virtualbox-backup.qcow2").write_bytes(b"backup-data")

            def convert(source, temporary):
                temporary.write_bytes(b"invalid-vdi")

            with self.paths(root)[0], self.paths(root)[1], self.paths(root)[2], self.paths(root)[3], patch.object(vbox, "_convert_qcow2_to_vdi", side_effect=convert), patch.object(vbox, "_verify_vdi", side_effect=vbox.ComputerError("unreadable VDI")):
                with self.assertRaises(vbox.ComputerError):
                    provisioning.ensure_disk({"system": "windows", "machine": "amd64"})
            self.assertFalse((root / "company-computer.vdi").exists())
            self.assertEqual(list(root.glob(".company-computer.vdi.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
