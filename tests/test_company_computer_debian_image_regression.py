import unittest

from agentie.core import company_computer as cc


class CompanyComputerDebianImageRegressionTests(unittest.TestCase):
    def test_new_x86_company_computers_use_generic_not_genericcloud_image(self):
        profile = {"machine": "x86_64"}
        filename = cc._debian_filename(profile)
        self.assertEqual(filename, "debian-13-generic-amd64.qcow2")
        self.assertNotIn("genericcloud", filename)
        self.assertIn("/trixie/latest/debian-13-generic-amd64.qcow2", cc._debian_url(profile))

    def test_new_arm_company_computers_use_generic_not_genericcloud_image(self):
        profile = {"machine": "arm64"}
        filename = cc._debian_filename(profile)
        self.assertEqual(filename, "debian-13-generic-arm64.qcow2")
        self.assertNotIn("genericcloud", filename)

    def test_generic_image_uses_separate_cache_and_does_not_touch_persistent_disk(self):
        self.assertEqual(cc.BASE_IMAGE.name, "debian-generic-base.qcow2")
        self.assertEqual(cc.DISK.name, "company-computer.qcow2")
        self.assertNotEqual(cc.BASE_IMAGE, cc.DISK)


if __name__ == "__main__":
    unittest.main()
