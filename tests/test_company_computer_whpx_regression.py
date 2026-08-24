import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import company_computer as cc
from agentie.core import company_computer_whpx  # noqa: F401 - registers compatibility wrapper


class CompanyComputerWHPXRegressionTests(unittest.TestCase):
    def _config(self, accelerator="whpx", machine="x86_64"):
        return {
            "profile": {
                "system": "windows",
                "machine": machine,
                "logical_cpus": 4,
                "memory_mb": 8192,
                "vm_ram_mb": 2048,
                "vm_vcpus": 2,
                "low_end": False,
            },
            "qemu": "qemu-system-x86_64",
            "acceleration": {"accelerator": accelerator},
        }

    def test_windows_whpx_uses_stable_q35_virtio_profile_without_cpu_host(self):
        args = cc._qemu_args(self._config())
        joined = " ".join(args)
        self.assertIn("-accel whpx,kernel-irqchip=off", joined)
        self.assertNotIn("-cpu host", joined)
        self.assertIn("-machine q35", joined)
        self.assertIn("-device virtio-vga", joined)
        self.assertNotIn("-vga std", joined)

    def test_windows_whpx_forces_single_vcpu(self):
        args = cc._qemu_args(self._config())
        smp_index = args.index("-smp")
        self.assertEqual(args[smp_index + 1], "1")

    def test_non_whpx_x86_keeps_cpu_host_vcpus_q35_and_virtio_vga(self):
        args = cc._qemu_args(self._config(accelerator="kvm"))
        joined = " ".join(args)
        self.assertIn("-cpu host", joined)
        self.assertIn("-machine q35", joined)
        self.assertIn("-device virtio-vga", joined)
        smp_index = args.index("-smp")
        self.assertEqual(args[smp_index + 1], "2")
        accel_index = args.index("-accel")
        self.assertEqual(args[accel_index + 1], "kvm")

    def test_tcg_uses_emulated_cpu_instead_of_unsupported_host_cpu(self):
        args = cc._qemu_args(self._config(accelerator="tcg"))
        joined = " ".join(args)
        self.assertIn("-accel tcg", joined)
        self.assertIn("-cpu max", joined)
        self.assertNotIn("-cpu host", joined)
        self.assertIn("-vga std", joined)
        self.assertNotIn("-device virtio-vga", joined)

    def test_whpx_fix_keeps_persistent_disk_and_guest_agent_channel(self):
        args = cc._qemu_args(self._config())
        joined = " ".join(args)
        self.assertIn(str(cc.DISK), joined)
        self.assertIn(f"port={cc.QGA_PORT}", joined)
        self.assertIn("org.qemu.guest_agent.0", joined)

    def test_effective_launch_arguments_are_written_to_qemu_log(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / "qemu.log"
            with patch.object(cc, "LOG_FILE", log):
                args = cc._qemu_args(self._config())
            text = log.read_text(encoding="utf-8")
        self.assertIn("=== Agentie QEMU launch ===", text)
        self.assertIn("-machine q35", text)
        self.assertIn("-device virtio-vga", text)
        self.assertIn("-accel whpx,kernel-irqchip=off", text)
        self.assertNotIn("-cpu host", text)
        self.assertEqual(args[args.index("-smp") + 1], "1")


if __name__ == "__main__":
    unittest.main()
