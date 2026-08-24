from __future__ import annotations

import base64
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import company_computer_backend as backend
from agentie.core import company_computer_virtualbox as vbox
from agentie.core import company_computer_virtualbox_provisioning as provisioning


class CompanyComputerVirtualBoxRegressionTests(unittest.TestCase):
    def test_backend_selection_defaults_by_platform(self):
        with patch.dict(os.environ, {"AGENTIE_COMPUTER_BACKEND": ""}):
            self.assertEqual(backend.backend_name("Windows"), "virtualbox")
            self.assertEqual(backend.backend_name("Darwin"), "qemu")
            self.assertEqual(backend.backend_name("Linux"), "qemu")

    def test_backend_override_remains_available_for_advanced_recovery(self):
        with patch.dict(os.environ, {"AGENTIE_COMPUTER_BACKEND": "qemu"}):
            self.assertEqual(backend.backend_name("Windows"), "qemu")
        with patch.dict(os.environ, {"AGENTIE_COMPUTER_BACKEND": "virtualbox"}):
            self.assertEqual(backend.backend_name("Linux"), "virtualbox")

    def test_existing_vdi_is_never_recreated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            disk = root / "company-computer.vdi"
            disk.write_bytes(b"persistent-user-data")
            ok = subprocess.CompletedProcess([], 0, stdout="UUID: test", stderr="")
            with (
                patch.object(vbox, "DISK", disk),
                patch.object(vbox, "_run", return_value=ok),
                patch.object(vbox, "_run_checked", return_value=ok),
            ):
                result = provisioning.ensure_disk({"system": "windows", "machine": "amd64"})
            self.assertEqual(result, disk)
            self.assertEqual(disk.read_bytes(), b"persistent-user-data")

    def test_existing_qcow2_is_backed_up_and_preserved_before_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            disk = root / "company-computer.vdi"
            old = root / "company-computer.qcow2"
            backup = root / "company-computer.pre-virtualbox-backup.qcow2"
            old.write_bytes(b"old-persistent-machine")

            def convert(source: Path, destination: Path) -> None:
                self.assertEqual(source, old)
                self.assertTrue(old.exists())
                self.assertTrue(backup.exists())
                destination.write_bytes(b"migrated")

            with (
                patch.object(vbox, "DISK", disk),
                patch.object(vbox, "OLD_QCOW2", old),
                patch.object(vbox, "OLD_QCOW2_BACKUP", backup),
                patch.object(vbox, "_convert_qcow2_to_vdi", side_effect=convert),
                patch.object(vbox, "_run", return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")),
                patch.object(vbox, "_run_checked", return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")),
            ):
                result = provisioning.ensure_disk({"system": "windows", "machine": "amd64"})
            self.assertEqual(result, disk)
            self.assertEqual(old.read_bytes(), b"old-persistent-machine")
            self.assertEqual(backup.read_bytes(), b"old-persistent-machine")
            self.assertEqual(disk.read_bytes(), b"migrated")

    def test_migrated_vdi_is_unregistered_before_atomic_publish_then_registered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staging = root / "company-computer.vdi.migration-part"
            destination = root / "company-computer.vdi"
            staging.write_bytes(b"verified-migration")
            calls: list[list[str]] = []

            def checked(args, **kwargs):
                calls.append(list(args))
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

            with patch.object(vbox, "_run_checked", side_effect=checked):
                vbox._finalize_vdi(staging, destination)
            self.assertEqual(destination.read_bytes(), b"verified-migration")
            self.assertEqual(
                [call[0] for call in calls],
                ["closemedium", "openmedium", "showmediuminfo"],
            )
            self.assertEqual(calls[0][-1], str(staging))
            self.assertEqual(calls[1][-1], str(destination))

    def test_stale_unregistered_machine_folder_is_preserved_before_create(self):
        with tempfile.TemporaryDirectory() as tmp:
            machine_root = Path(tmp) / "machines"
            stale = machine_root / vbox.VM_NAME
            stale.mkdir(parents=True)
            (stale / f"{vbox.VM_NAME}.vbox").write_text("settings", encoding="utf-8")
            with patch.object(vbox, "_vm_exists", return_value=False):
                preserved = provisioning._preserve_stale_machine_folder(machine_root)
            self.assertIsNotNone(preserved)
            self.assertFalse(stale.exists())
            self.assertEqual(
                (preserved / f"{vbox.VM_NAME}.vbox").read_text(encoding="utf-8"),
                "settings",
            )

    def test_existing_final_vdi_is_registered_on_idempotent_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            disk = Path(tmp) / "company-computer.vdi"
            disk.write_bytes(b"persistent-user-data")
            missing = subprocess.CompletedProcess([], 1, stdout="", stderr="not registered")
            calls: list[list[str]] = []
            def checked(args, **kwargs):
                calls.append(list(args))
                return subprocess.CompletedProcess(args, 0, stdout="UUID: test", stderr="")
            with (
                patch.object(vbox, "DISK", disk),
                patch.object(vbox, "_run", return_value=missing),
                patch.object(vbox, "_run_checked", side_effect=checked),
            ):
                provisioning.ensure_disk({"system": "windows", "machine": "amd64"})
            self.assertEqual(disk.read_bytes(), b"persistent-user-data")
            self.assertEqual([call[0] for call in calls], ["openmedium", "showmediuminfo"])

    def test_migration_seed_identity_is_new_and_stable_across_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / "company-computer.qcow2"
            old.write_bytes(b"persistent")
            with (
                patch.object(vbox, "ROOT", root),
                patch.object(vbox, "SEED_ISO", root / "seed.iso"),
                patch.object(vbox, "OLD_QCOW2", old),
                patch.object(vbox, "OLD_QCOW2_BACKUP", root / "backup.qcow2"),
                patch.object(vbox, "_cloud_init_user_data", return_value="#cloud-config\n"),
                patch.object(vbox, "SEED_VERSION", provisioning.SEED_VERSION),
            ):
                vbox.ensure_seed_iso()
                import pycdlib
                iso = pycdlib.PyCdlib()
                iso.open(str(vbox.SEED_ISO))
                output = root / "meta-data"
                iso.get_file_from_iso(str(output), joliet_path="/meta-data")
                iso.close()
                first = output.read_text(encoding="utf-8")
                vbox.ensure_seed_iso()
            self.assertIn("instance-id: agentie-company-computer-vbox-migration-v4", first)
            self.assertNotIn("instance-id: agentie-company-computer\n", first)

    def test_vbox_failure_reports_exact_setup_stage(self):
        failed = subprocess.CompletedProcess(["VBoxManage"], 1, stdout="", stderr="bad config")
        with patch.object(vbox, "_run", return_value=failed):
            with self.assertRaises(vbox.ComputerError) as ctx:
                vbox._run_checked(["modifyvm", vbox.VM_NAME], stage="vm_configure")
        message = str(ctx.exception).lower()
        self.assertIn("vm_configure", message)
        self.assertIn("bad config", message)

    def test_running_vm_does_not_imply_display_or_browser_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(vbox, "ROOT", root),
                patch.object(vbox, "STATE_DB", root / "state.sqlite3"),
                patch.object(vbox, "DISK", root / "company-computer.vdi"),
                patch.object(vbox, "OLD_QCOW2", root / "company-computer.qcow2"),
                patch.object(vbox, "OLD_QCOW2_BACKUP", root / "backup.qcow2"),
                patch.object(vbox, "vbox_binary", return_value="VBoxManage.exe"),
                patch.object(vbox, "_vm_state", return_value="running"),
                patch.object(vbox, "_port_open", return_value=False),
                patch.object(vbox, "_cdp_ready", return_value=False),
            ):
                result = vbox.status()
            self.assertTrue(result["running"])
            self.assertFalse(result["display_ready"])
            self.assertFalse(result["browser_ready"])

    def test_readiness_pipeline_requires_guest_desktop_display_and_browser(self):
        stages: list[str] = []

        def fake_wait(stage, predicate, timeout, message):
            stages.append(stage)

        with (
            patch.object(vbox, "_wait", side_effect=fake_wait),
            patch.object(vbox, "_start_display_server"),
            patch.object(vbox, "_start_vnc_websocket_bridge"),
            patch.object(vbox, "_port_open", return_value=True),
            patch.object(vbox, "_update"),
        ):
            vbox._wait_until_ready()
        self.assertEqual(stages, ["GUEST_READY", "DESKTOP_READY", "DISPLAY_READY", "BROWSER_READY"])

    def test_nat_forwarding_is_localhost_only(self):
        checked: list[list[str]] = []

        def capture(args, **kwargs):
            checked.append(list(args))
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        with patch.object(vbox, "_run_checked", side_effect=capture), patch.object(vbox, "_run", return_value=subprocess.CompletedProcess([], 1, stdout="", stderr="")):
            provisioning._set_nat_rule("cdp", 9222, 9222)
            provisioning._set_nat_rule("vnc", 5901, 5900)
        rendered = "\n".join(" ".join(command) for command in checked)
        self.assertIn("cdp,tcp,127.0.0.1,9222,,9222", rendered)
        self.assertIn("vnc,tcp,127.0.0.1,5901,,5900", rendered)
        self.assertNotIn("0.0.0.0", rendered)

    def test_provisioning_uses_host_guest_additions_iso_not_unstable_debian_package(self):
        with patch.object(vbox, "guest_credentials", return_value=("agentie", "temporary-bootstrap-password")):
            cloud_init = provisioning._cloud_init_user_data()
        self.assertIn("VBoxLinuxAdditions.run", cloud_init)
        self.assertIn("agentie-xorg.service", cloud_init)
        self.assertIn("agentie-vnc.service", cloud_init)
        self.assertNotIn("virtualbox-guest-utils", cloud_init)

    def test_guest_credential_is_not_saved_as_plaintext(self):
        with tempfile.TemporaryDirectory() as tmp:
            credential_file = Path(tmp) / "vbox-guest-credentials.bin"
            with patch.object(vbox, "CREDENTIALS_FILE", credential_file):
                password = vbox._guest_password()
                stored = credential_file.read_bytes()
            self.assertNotIn(password.encode("utf-8"), stored)
            self.assertEqual(credential_file.suffix, ".bin")

    def test_compressed_generic_image_is_used_for_new_installs(self):
        self.assertEqual(provisioning.ARCHIVE_NAME, "debian-13-generic-amd64.tar.xz")
        self.assertEqual(provisioning.RAW_MEMBER_NAME, "debian-13-generic-amd64.raw")
        self.assertNotIn("genericcloud", provisioning.ARCHIVE_NAME)

    def test_desktop_and_browser_use_backend_facade(self):
        desktop = (Path.cwd() / "agentie" / "core" / "desktop_runtime.py").read_text(encoding="utf-8")
        browser = (Path.cwd() / "agentie" / "core" / "browser_automation.py").read_text(encoding="utf-8")
        session = (Path.cwd() / "agentie" / "core" / "computer_session.py").read_text(encoding="utf-8")
        self.assertIn("company_computer_backend", desktop)
        self.assertIn("company_computer_backend", browser)
        self.assertIn("company_computer_backend", session)

    def test_all_shared_runtime_layers_use_backend_facade(self):
        for name in (
            "company_computer_files.py",
            "company_computer_desktop.py",
            "company_computer_idle.py",
            "company_computer_guest_setup.py",
        ):
            source = (Path.cwd() / "agentie" / "core" / name).read_text(encoding="utf-8")
            self.assertIn("company_computer_backend", source, name)
            self.assertNotIn("from agentie.core import company_computer as computer", source, name)

    def test_backend_neutral_upload_uses_guest_exec(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "payload.bin"
            source.write_bytes(b"backend-neutral")
            with patch.object(backend, "guest_exec", return_value={"exitcode": 0}) as guest:
                total = backend.guest_upload(source, "/home/agentie/payload.bin", chunk_bytes=1024)
        self.assertEqual(total, len(b"backend-neutral"))
        self.assertEqual(guest.call_args.args[0][0], "/usr/bin/python3")

    def test_backend_neutral_download_decodes_guest_stdout(self):
        chunks = [b"backend-neutral", b""]
        def guest_exec(*args, **kwargs):
            inner = base64.b64encode(chunks.pop(0))
            return {"exitcode": 0, "out-data": base64.b64encode(inner).decode("ascii")}
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "payload.bin"
            with patch.object(backend, "guest_exec", side_effect=guest_exec):
                total = backend.guest_download("/home/agentie/payload.bin", destination, max_bytes=100)
            self.assertEqual(destination.read_bytes(), b"backend-neutral")
        self.assertEqual(total, len(b"backend-neutral"))

    def test_virtualbox_backend_contains_no_anti_bot_evasion(self):
        source = (Path.cwd() / "agentie" / "core" / "company_computer_virtualbox.py").read_text(encoding="utf-8").lower()
        provisioning_source = (Path.cwd() / "agentie" / "core" / "company_computer_virtualbox_provisioning.py").read_text(encoding="utf-8").lower()
        combined = source + "\n" + provisioning_source
        for forbidden in ("playwright-stealth", "navigator.webdriver", "residential proxy", "automationcontrolled"):
            self.assertNotIn(forbidden, combined)


if __name__ == "__main__":
    unittest.main()
