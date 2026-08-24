import unittest
from unittest.mock import patch

from agentie.core import company_computer as computer
from agentie.core import company_computer_windows_accel as windows_accel


class CompanyComputerWindowsAccelerationRegressionTests(unittest.TestCase):
    def profile(self):
        return {
            "system": "windows",
            "machine": "x86_64",
            "logical_cpus": 4,
            "memory_mb": 8192,
            "vm_ram_mb": 2048,
            "vm_vcpus": 2,
            "low_end": False,
        }

    def test_qemu_whpx_support_is_enough_without_dism_elevation(self):
        with patch.object(computer, "_accel_help", return_value={"whpx", "tcg"}), patch.object(
            computer, "_whpx_feature_enabled", return_value=False
        ):
            result = windows_accel.acceleration("qemu-system-x86_64", self.profile())
        self.assertTrue(result["available"])
        self.assertEqual(result["accelerator"], "whpx")

    def test_windows_still_does_not_silently_fall_back_to_tcg(self):
        with patch.object(computer, "_accel_help", return_value={"tcg"}), patch.object(
            computer, "ALLOW_TCG", False
        ):
            result = windows_accel.acceleration("qemu-system-x86_64", self.profile())
        self.assertFalse(result["available"])
        self.assertEqual(result["accelerator"], "whpx")
        self.assertIn("WHPX", result["reason"])

    def test_explicit_tcg_mode_wins_when_windows_hypervisor_is_unavailable(self):
        with patch.object(computer, "_accel_help", return_value={"whpx", "tcg"}), patch.object(
            computer, "_whpx_feature_enabled", return_value=False
        ), patch.object(computer, "ALLOW_TCG", True):
            result = windows_accel.acceleration("qemu-system-x86_64", self.profile())
        self.assertTrue(result["available"])
        self.assertEqual(result["accelerator"], "tcg")


if __name__ == "__main__":
    unittest.main()
