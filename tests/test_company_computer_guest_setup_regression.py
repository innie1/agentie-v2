import base64
import unittest
from unittest.mock import patch

from agentie.core import company_computer_guest_setup as setup


class CompanyComputerGuestSetupRegressionTests(unittest.TestCase):
    def test_repair_uses_managed_xorg_instead_of_startx_loop(self):
        script = setup._repair_script()
        self.assertIn("cat >/etc/systemd/system/agentie-xorg.service", script)
        self.assertIn("ExecStart=/usr/bin/Xorg :0 -noreset -nolisten tcp -ac vt1", script)
        self.assertIn("Requires=agentie-xorg.service", script)
        self.assertIn("ExecStart=/home/agentie/.agentie-desktop-session.sh", script)
        self.assertNotIn("ExecStart=/usr/bin/startx", script)
        self.assertIn("systemctl restart agentie-xorg.service", script)
        self.assertIn("systemctl restart agentie-desktop.service", script)

    def test_repair_installs_complete_desktop_stack_for_partial_persistent_disk(self):
        script = setup._repair_script()
        for package in (
            "xserver-xorg",
            "xserver-xorg-core",
            "xserver-xorg-video-all",
            "openbox",
            "dbus",
            "dbus-x11",
            "pcmanfm",
            "xterm",
            "chromium",
            "qemu-guest-agent",
            "xdotool",
        ):
            self.assertIn(package, script)

    def test_repair_recovers_interrupted_debian_package_state_first(self):
        script = setup._repair_script()
        self.assertLess(script.index("apt_retry -f install -y"), script.index("apt_retry install -y --no-install-recommends"))
        self.assertIn("apt_retry install --reinstall -y libmpc3", script)
        self.assertIn("dpkg -V chromium", script)
        self.assertIn("chromium-common_*.deb", script)
        self.assertIn("Acquire::https::Timeout=20", script)
        self.assertNotIn("google-chrome-stable", script)
        self.assertIn("need_packages=0", script)
        self.assertIn("libmpc3_*.deb", script)
        self.assertIn("dpkg-query -W", script)
        self.assertIn("DNS=10.0.2.3", script)

    def test_repair_preserves_privilege_boundary_and_persistence(self):
        script = setup._repair_script()
        self.assertIn("gpasswd -d agentie sudo", script)
        self.assertIn("/etc/sudoers.d", script)
        self.assertNotIn("systemctl restart qemu-guest-agent", script)
        self.assertIn("touch /var/lib/agentie/runtime-v7", script)
        self.assertNotIn("qemu-img", script)
        self.assertNotIn("rm -f /home/agentie/.config/chromium-agentie", script)

    def test_desktop_session_keeps_openbox_as_long_running_process(self):
        script = setup._repair_script()
        self.assertIn("/usr/bin/dbus-run-session", script)
        self.assertIn("exec /usr/bin/openbox --sm-disable", script)
        self.assertNotIn("openbox-session", script)
        self.assertNotIn("dbus-launch --exit-with-session", script)
        self.assertIn("Restart=on-failure", script)

    def test_desktop_session_keeps_persistent_chromium_profile(self):
        script = setup._repair_script()
        self.assertIn('/usr/bin/chromium --user-data-dir=/home/agentie/.config/chromium-agentie', script)
        self.assertIn('--password-store=basic', script)
        self.assertNotIn('google-chrome-stable', script)
        self.assertIn("--restore-last-session", script)
        self.assertIn("pcmanfm --desktop", script)

    def test_repair_surfaces_xorg_kernel_and_desktop_diagnostics(self):
        script = setup._repair_script()
        diagnostics = " ".join(setup._desktop_diagnostics_command())
        self.assertIn("systemctl status agentie-xorg.service --no-pager -l", script)
        self.assertIn("systemctl status agentie-desktop.service --no-pager -l", script)
        self.assertIn("journalctl -u agentie-xorg.service", diagnostics)
        self.assertIn("/var/log/Xorg.0.log", diagnostics)
        self.assertIn("uname -a", diagnostics)
        self.assertIn("/dev/dri", diagnostics)
        self.assertIn("virtio_gpu", diagnostics)

    def test_health_checks_real_x11_query_not_socket_only(self):
        command = " ".join(setup._desktop_health_command())
        self.assertIn("agentie-xorg.service", command)
        self.assertIn("agentie-desktop.service", command)
        self.assertIn("xdotool getdisplaygeometry", command)

    def test_full_graphics_kernel_is_noop_when_dri_already_available(self):
        completed = {"exited": True, "exitcode": 0}
        with patch.object(setup.computer, "guest_exec", return_value=completed) as guest:
            setup._ensure_full_graphics_kernel(60)
        self.assertEqual(guest.call_count, 1)
        self.assertIn("/dev/dri/card0", guest.call_args.args[0][-1])

    def test_cloud_kernel_is_upgraded_and_guest_rebooted_in_place(self):
        cloud_kernel = {"exited": True, "exitcode": 10}
        completed = {"exited": True, "exitcode": 0}
        with patch.object(
            setup.computer,
            "guest_exec",
            side_effect=[cloud_kernel, completed, completed, completed],
        ) as guest, patch.object(setup.time, "sleep"), patch.object(setup, "_wait_for_qga") as wait_qga:
            setup._ensure_full_graphics_kernel(90)
        install_command = guest.call_args_list[1].args[0][-1]
        reboot_command = guest.call_args_list[2].args[0][-1]
        verify_command = guest.call_args_list[3].args[0][-1]
        self.assertIn("apt-get install -y --no-install-recommends linux-image-amd64", install_command)
        self.assertIn("systemctl reboot", reboot_command)
        self.assertIn("modprobe virtio_gpu", verify_command)
        self.assertIn("/dev/dri/card0", verify_command)
        wait_qga.assert_called_once()

    def test_first_use_repairs_in_place_then_checks_health(self):
        status = {"computer_id": "company-default", "state": "READY", "disk_exists": True}
        completed = {"exited": True, "exitcode": 0}
        with patch.object(setup.computer, "start", return_value=status) as start, \
             patch.object(setup, "_wait_for_qga") as wait_qga, \
             patch.object(setup, "_wait_for_cloud_init") as wait_cloud, \
             patch.object(setup, "_ensure_full_graphics_kernel") as ensure_kernel, \
             patch.object(setup, "_marker_exists", return_value=False), \
             patch.object(setup.computer, "guest_exec", return_value=completed) as guest, \
             patch.object(setup.computer, "touch_activity") as touch, \
             patch.object(setup.computer, "status", return_value=status):
            result = setup.ensure_guest_runtime()
        start.assert_called_once()
        wait_qga.assert_called_once()
        wait_cloud.assert_called_once()
        ensure_kernel.assert_called_once()
        self.assertGreaterEqual(guest.call_count, 2)
        repair_argv = guest.call_args_list[0].args[0]
        self.assertEqual(repair_argv[:2], ["/bin/bash", "-lc"])
        self.assertIn("runtime-v7", repair_argv[-1])
        self.assertNotIn("qemu-img", repair_argv[-1])
        touch.assert_called_once()
        self.assertEqual(result["computer_id"], "company-default")

    def test_prepared_unhealthy_guest_reapplies_idempotent_repair(self):
        inactive = {"exited": True, "exitcode": 3}
        completed = {"exited": True, "exitcode": 0}
        status = {"computer_id": "company-default", "state": "READY"}
        with patch.object(setup.computer, "start", return_value=status), \
             patch.object(setup, "_wait_for_qga"), \
             patch.object(setup, "_wait_for_cloud_init"), \
             patch.object(setup, "_ensure_full_graphics_kernel"), \
             patch.object(setup, "_marker_exists", return_value=True), \
             patch.object(setup.computer, "guest_exec", side_effect=[inactive, completed, completed]) as guest, \
             patch.object(setup.computer, "touch_activity"), \
             patch.object(setup.computer, "status", return_value=status):
            setup.ensure_guest_runtime()
        repair_argv = guest.call_args_list[1].args[0]
        self.assertEqual(repair_argv[:2], ["/bin/bash", "-lc"])
        self.assertIn("agentie-xorg.service", repair_argv[-1])

    def test_failed_repair_surfaces_decoded_guest_error(self):
        failed = {
            "exited": True,
            "exitcode": 1,
            "err-data": base64.b64encode(b"Xorg failed to create display :0").decode(),
        }
        with patch.object(setup.computer, "start", return_value={}), \
             patch.object(setup, "_wait_for_qga"), \
             patch.object(setup, "_wait_for_cloud_init"), \
             patch.object(setup, "_ensure_full_graphics_kernel"), \
             patch.object(setup, "_marker_exists", return_value=False), \
             patch.object(setup.computer, "guest_exec", return_value=failed):
            with self.assertRaises(setup.computer.ComputerError) as ctx:
                setup.ensure_guest_runtime()
        self.assertIn("Xorg failed", str(ctx.exception))

    def test_cloud_init_wait_uses_guest_channel(self):
        completed = {"exited": True, "exitcode": 0}
        with patch.object(setup.computer, "guest_exec", return_value=completed) as guest:
            setup._wait_for_cloud_init(timeout=90)
        argv = guest.call_args.args[0]
        self.assertEqual(argv[:2], ["/bin/bash", "-lc"])
        self.assertIn("cloud-init status --wait", argv[-1])

    def test_qga_timeout_is_actionable(self):
        with patch.object(setup.time, "time", side_effect=[0, 31]):
            with self.assertRaises(setup.computer.ComputerError) as ctx:
                setup._wait_for_qga(timeout=1)
        self.assertIn("guest automation service did not become ready", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
