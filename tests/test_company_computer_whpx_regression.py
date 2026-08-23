import unittest

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

    def test_windows_whpx_does_not_pass_cpu_host(self):
        args = cc._qemu_args(self._config())
        joined = " ".join(args)
        self.assertIn("-accel whpx", joined)
        self.assertNotIn("-cpu host", joined)
        self.assertIn("-machine q35", joined)

    def test_windows_whpx_forces_single_vcpu_for_apic_stability(self):
        args = cc._qemu_args(self._config())
        smp_index = args.index("-smp")
        self.assertEqual(args[smp_index + 1], "1")

    def test_non_whpx_x86_keeps_cpu_host_and_configured_vcpus(self):
        args = cc._qemu_args(self._config(accelerator="kvm"))
        self.assertIn("-cpu host", " ".join(args))
        smp_index = args.index("-smp")
        self.assertEqual(args[smp_index + 1], "2")

    def test_whpx_fix_keeps_persistent_disk_and_guest_agent_channel(self):
        args = cc._qemu_args(self._config())
        joined = " ".join(args)
        self.assertIn(str(cc.DISK), joined)
        self.assertIn(f"port={cc.QGA_PORT}", joined)
        self.assertIn("org.qemu.guest_agent.0", joined)


if __name__ == "__main__":
    unittest.main()
