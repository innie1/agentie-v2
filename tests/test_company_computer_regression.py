import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agentie.core import company_computer as cc


class CompanyComputerRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patches = [
            patch.object(cc, "ROOT", root),
            patch.object(cc, "STATE_DB", root / "state.sqlite3"),
            patch.object(cc, "DISK", root / "company-computer.qcow2"),
            patch.object(cc, "BASE_IMAGE", root / "runtime" / "debian-base.qcow2"),
            patch.object(cc, "SEED_ISO", root / "cloud-init.iso"),
            patch.object(cc, "PID_FILE", root / "qemu.pid"),
            patch.object(cc, "LOG_FILE", root / "qemu.log"),
        ]
        for item in self.patches:item.start()
        cc._ensure_db()

    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.temp.cleanup()

    def profile(self, system="windows", machine="x86_64"):
        return {"system":system,"machine":machine,"logical_cpus":4,"memory_mb":8192,"vm_ram_mb":2048,"vm_vcpus":2,"low_end":False}

    def test_state_database_connections_are_closed_after_each_operation(self):
        cc._update(state="IDLE")
        self.assertTrue(cc.STATE_DB.exists())
        cc.STATE_DB.unlink()
        self.assertFalse(cc.STATE_DB.exists())
        cc._ensure_db()
        self.assertTrue(cc.STATE_DB.exists())

    def test_windows_selects_whpx(self):
        with patch.object(cc,"_accel_help",return_value={"whpx","tcg"}):
            result=cc.acceleration("qemu",self.profile("windows"))
        self.assertTrue(result["available"]);self.assertEqual(result["accelerator"],"whpx")

    def test_macos_selects_hvf(self):
        with patch.object(cc,"_accel_help",return_value={"hvf","tcg"}):
            result=cc.acceleration("qemu",self.profile("darwin","arm64"))
        self.assertEqual(result["accelerator"],"hvf")

    def test_linux_selects_kvm(self):
        with patch.object(cc,"_accel_help",return_value={"kvm","tcg"}), patch.object(cc.os.path,"exists",return_value=True), patch.object(cc.os,"access",return_value=True):
            result=cc.acceleration("qemu",self.profile("linux"))
        self.assertEqual(result["accelerator"],"kvm")

    def test_unavailable_acceleration_does_not_silently_use_tcg(self):
        with patch.object(cc,"_accel_help",return_value={"tcg"}), patch.object(cc,"ALLOW_TCG",False):
            result=cc.acceleration("qemu",self.profile("windows"))
        self.assertFalse(result["available"]);self.assertEqual(result["accelerator"],"whpx");self.assertIn("Hypervisor",result["action"])

    def test_explicit_compatibility_mode_can_use_tcg(self):
        with patch.object(cc,"_accel_help",return_value={"tcg"}), patch.object(cc,"ALLOW_TCG",True):
            result=cc.acceleration("qemu",self.profile("windows"))
        self.assertEqual(result["accelerator"],"tcg");self.assertTrue(result["compatibility_mode"])

    def test_low_end_resources_use_one_vcpu_and_about_one_gb(self):
        memory=MagicMock(total=3*1024*1024*1024)
        with patch.object(cc.platform,"system",return_value="Windows"), patch.object(cc.platform,"machine",return_value="AMD64"), patch.object(cc.psutil,"cpu_count",return_value=2), patch.object(cc.psutil,"virtual_memory",return_value=memory):
            result=cc.host_profile()
        self.assertEqual(result["vm_vcpus"],1);self.assertEqual(result["vm_ram_mb"],1024);self.assertTrue(result["low_end"])

    def test_qemu_detection_prefers_bundled_runtime(self):
        profile=self.profile("linux")
        fake=Path.cwd()/"runtime"/"qemu"/("qemu-system-x86_64.exe" if os.name=="nt" else "qemu-system-x86_64")
        original_exists=Path.exists
        def exists(path):return True if path==fake else original_exists(path)
        with patch.object(Path,"exists",exists):
            self.assertEqual(cc.qemu_binary(profile),str(fake))

    def test_existing_qcow2_is_never_recreated(self):
        cc.DISK.parent.mkdir(parents=True,exist_ok=True);cc.DISK.write_bytes(b"persistent-data")
        with patch.object(cc.subprocess,"run") as run:
            result=cc.ensure_disk("qemu-img",self.profile("linux"))
        self.assertEqual(result,cc.DISK);self.assertEqual(cc.DISK.read_bytes(),b"persistent-data");run.assert_not_called()

    def test_vm_args_use_persistent_disk_display_cdp_and_acceleration(self):
        cc.DISK.write_bytes(b"disk");cc.SEED_ISO.write_bytes(b"seed")
        config={"profile":self.profile("windows"),"qemu":"qemu-system-x86_64","acceleration":{"accelerator":"whpx"}}
        args=cc._qemu_args(config)
        joined=" ".join(args)
        self.assertIn("-accel whpx",joined);self.assertIn("-cpu Westmere",joined);self.assertIn(str(cc.DISK),joined);self.assertIn("websocket=",joined);self.assertIn(f"hostfwd=tcp:127.0.0.1:{cc.CDP_PORT}-:{cc.CDP_PORT}",joined)

    def test_shared_company_computer_has_one_persistent_identity(self):
        with patch.object(cc,"_is_pid_alive",return_value=False):
            info=cc.status()
        self.assertEqual(info["computer_id"],"company-default");self.assertTrue(info["persistent"]);self.assertEqual(info["disk_path"],str(cc.DISK))

    def test_agent_ownership_handoff_user_takeover_and_return(self):
        with patch.object(cc,"start",return_value={}):
            first=cc.acquire_agent("agt_sales","job-1")
            handed=cc.handoff_agent("agt_sales","agt_research","job-2")
            required=cc.request_user_takeover("agt_research","Complete 2FA")
            user=cc.acquire_user()
            returned=cc.continue_agent()
        self.assertEqual(first["controller_agent_id"],"agt_sales")
        self.assertEqual(handed["controller_agent_id"],"agt_research")
        self.assertEqual(required["state"],"USER_REQUIRED")
        self.assertEqual(user["state"],"USER_CONTROL")
        self.assertEqual(returned["state"],"AGENT_CONTROL");self.assertEqual(returned["controller_agent_id"],"agt_research")

    def test_second_agent_cannot_steal_live_control(self):
        with patch.object(cc,"start",return_value={}):
            cc.acquire_agent("agt_one")
            with self.assertRaises(cc.ComputerError):cc.acquire_agent("agt_two")

    def test_suspend_refuses_while_controlled(self):
        cc._update(state="AGENT_CONTROL",controller_type="agent",controller_agent_id="agt_one",vm_pid=123)
        with patch.object(cc,"_is_pid_alive",return_value=True):
            with self.assertRaises(cc.ComputerError):cc.suspend()

    def test_host_restart_recovery_keeps_disk_and_resets_dead_runtime(self):
        cc.DISK.write_bytes(b"files-cookies-apps")
        cc._update(state="AGENT_CONTROL",controller_type="agent",controller_agent_id="agt_one",vm_pid=999)
        with patch.object(cc,"_is_pid_alive",return_value=False):info=cc.status()
        self.assertEqual(info["state"],"STOPPED");self.assertTrue(cc.DISK.exists());self.assertEqual(cc.DISK.read_bytes(),b"files-cookies-apps")

    def test_guest_bootstrap_persists_browser_files_downloads_and_apps_on_disk(self):
        cloud=cc._cloud_init_user_data()
        self.assertIn("chromium-agentie",cloud);self.assertIn("--restore-last-session",cloud);self.assertIn("/home/agentie/Downloads",cloud);self.assertIn("pcmanfm",cloud);self.assertIn("qemu-guest-agent",cloud)

    def test_display_is_qemu_native_vnc_websocket_not_old_stack(self):
        url=cc.display_url(view_only=True)
        self.assertIn("vnc.html",url);self.assertIn("view_only=1",url);self.assertIn(str(cc.VNC_WEBSOCKET_PORT),url)
        self.assertIn("host=127.0.0.1",url);self.assertTrue(url.endswith("&path="));self.assertNotIn("path=websockify",url)
        source=Path("agentie/core/company_computer.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("kasmvnc",source);self.assertNotIn("xfce",source);self.assertNotIn("wsl",source);self.assertNotIn("8444",source)


if __name__=="__main__":unittest.main()
