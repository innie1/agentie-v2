import base64
import unittest
from unittest.mock import patch

from agentie.core import company_computer_guest_setup as setup


class CompanyComputerGuestSetupRegressionTests(unittest.TestCase):
    def test_repair_script_hardens_headless_xorg_and_privilege_boundary(self):
        script = setup._repair_script()
        self.assertIn("xserver-xorg-legacy", script)
        self.assertIn("xdotool", script)
        self.assertIn("allowed_users=anybody", script)
        self.assertIn("needs_root_rights=yes", script)
        self.assertIn("gpasswd -d agentie sudo", script)
        self.assertIn("/etc/sudoers.d", script)
        self.assertIn("TTYPath=/dev/tty1", script)
        self.assertIn("systemctl restart agentie-desktop.service", script)
        self.assertNotIn("systemctl restart qemu-guest-agent", script)
        self.assertIn("touch /var/lib/agentie/runtime-v3", script)
        self.assertIn("pgrep -x apt-get", script)
        self.assertIn("dpkg --configure -a", script)

    def test_repair_installs_complete_desktop_stack_for_partial_persistent_disk(self):
        script = setup._repair_script()
        for package in ("xserver-xorg", "xinit", "openbox", "dbus-x11", "pcmanfm", "xterm", "chromium", "qemu-guest-agent"):
            self.assertIn(package, script)

    def test_repair_recreates_missing_desktop_service_and_xinit(self):
        script = setup._repair_script()
        self.assertIn("cat >/etc/systemd/system/agentie-desktop.service", script)
        self.assertIn("cat >/home/agentie/.xinitrc", script)
        self.assertIn("ExecStart=/usr/bin/startx /home/agentie/.xinitrc -- :0 -nolisten tcp vt1", script)
        self.assertIn("chromium --user-data-dir=/home/agentie/.config/chromium-agentie", script)
        self.assertIn("systemctl daemon-reload", script)
        self.assertIn("systemctl enable agentie-desktop.service", script)

    def test_repair_surfaces_systemd_status_and_journal_when_desktop_fails(self):
        script = setup._repair_script()
        self.assertIn("systemctl status agentie-desktop.service --no-pager -l", script)
        self.assertIn("journalctl -u agentie-desktop.service -n 80 --no-pager", script)

    def test_first_use_waits_for_cloud_init_then_repairs_in_place_without_recreating_disk(self):
        status = {"computer_id": "company-default", "state": "READY", "disk_exists": True}
        completed = {"exited": True, "exitcode": 0}
        with patch.object(setup.computer, "start", return_value=status) as start, patch.object(setup, "_wait_for_qga") as wait_qga, patch.object(setup, "_wait_for_cloud_init") as wait_cloud, patch.object(setup, "_marker_exists", return_value=False), patch.object(setup.computer, "guest_exec", return_value=completed) as guest, patch.object(setup.computer, "touch_activity") as touch, patch.object(setup.computer, "status", return_value=status):
            result = setup.ensure_guest_runtime()
        start.assert_called_once()
        wait_qga.assert_called_once()
        wait_cloud.assert_called_once()
        self.assertEqual(guest.call_count, 1)
        argv = guest.call_args.args[0]
        self.assertEqual(argv[:2], ["/bin/bash", "-lc"])
        self.assertIn("runtime-v3", argv[-1])
        self.assertNotIn("qemu-img", argv[-1])
        touch.assert_called_once()
        self.assertEqual(result["computer_id"], "company-default")

    def test_cloud_init_wait_uses_guest_channel(self):
        completed = {"exited": True, "exitcode": 0}
        with patch.object(setup.computer, "guest_exec", return_value=completed) as guest:
            setup._wait_for_cloud_init(timeout=90)
        argv = guest.call_args.args[0]
        self.assertEqual(argv[:2], ["/bin/bash", "-lc"])
        self.assertIn("cloud-init status --wait", argv[-1])

    def test_prepared_guest_only_checks_desktop_health_after_waits(self):
        active = {"exited": True, "exitcode": 0}
        status = {"computer_id": "company-default", "state": "READY"}
        with patch.object(setup.computer, "start", return_value=status), patch.object(setup, "_wait_for_qga"), patch.object(setup, "_wait_for_cloud_init"), patch.object(setup, "_marker_exists", return_value=True), patch.object(setup.computer, "guest_exec", return_value=active) as guest, patch.object(setup.computer, "touch_activity"), patch.object(setup.computer, "status", return_value=status):
            setup.ensure_guest_runtime()
        self.assertEqual(guest.call_count, 1)
        self.assertEqual(guest.call_args.args[0], ["/bin/systemctl", "is-active", "--quiet", "agentie-desktop.service"])

    def test_inactive_prepared_desktop_is_restarted(self):
        inactive = {"exited": True, "exitcode": 3}
        restarted = {"exited": True, "exitcode": 0}
        status = {"computer_id": "company-default", "state": "READY"}
        with patch.object(setup.computer, "start", return_value=status), patch.object(setup, "_wait_for_qga"), patch.object(setup, "_wait_for_cloud_init"), patch.object(setup, "_marker_exists", return_value=True), patch.object(setup.computer, "guest_exec", side_effect=[inactive, restarted]) as guest, patch.object(setup.computer, "touch_activity"), patch.object(setup.computer, "status", return_value=status):
            setup.ensure_guest_runtime()
        self.assertEqual(guest.call_args_list[1].args[0], ["/bin/systemctl", "restart", "agentie-desktop.service"])

    def test_failed_repair_surfaces_decoded_guest_error(self):
        failed = {
            "exited": True,
            "exitcode": 100,
            "err-data": base64.b64encode(b"Could not get lock /var/lib/dpkg/lock-frontend").decode(),
        }
        with patch.object(setup.computer, "start", return_value={}), patch.object(setup, "_wait_for_qga"), patch.object(setup, "_wait_for_cloud_init"), patch.object(setup, "_marker_exists", return_value=False), patch.object(setup.computer, "guest_exec", return_value=failed):
            with self.assertRaises(setup.computer.ComputerError) as ctx:
                setup.ensure_guest_runtime()
        self.assertIn("Could not get lock", str(ctx.exception))

    def test_qga_timeout_is_actionable(self):
        with patch.object(setup.time, "time", side_effect=[0, 31]):
            with self.assertRaises(setup.computer.ComputerError) as ctx:
                setup._wait_for_qga(timeout=1)
        self.assertIn("guest automation service did not become ready", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
