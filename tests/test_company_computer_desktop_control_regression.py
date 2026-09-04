import unittest
from unittest.mock import patch

from agentie.core import company_computer_desktop as desktop


class CompanyComputerDesktopControlRegressionTests(unittest.TestCase):
    def test_click_uses_guest_xdotool_and_session_owner(self):
        check = {"exited": True, "exitcode": 0}
        status = {"computer_id": "company-default", "state": "IDLE", "persistent": True}
        with patch.object(desktop, "ensure_guest_runtime", return_value=status) as prepare, patch.object(desktop.computer, "acquire_agent") as acquire, patch.object(desktop.computer, "release_control") as release, patch.object(desktop.computer, "guest_exec", side_effect=[check, check]) as guest, patch.object(desktop.computer, "touch_activity"), patch.object(desktop.computer, "status", return_value=status):
            result = desktop.desktop_click(420, 240, "agent:agt_sales:main")
        prepare.assert_called_once()
        acquire.assert_called_once_with("agt_sales")
        release.assert_called_once_with("agt_sales")
        argv = guest.call_args_list[1].args[0]
        self.assertIn("/usr/bin/xdotool", argv)
        self.assertEqual(argv[-6:], ["mousemove", "--sync", "420", "240", "click", "1"])
        self.assertEqual(result["computer_id"], "company-default")

    def test_typing_is_passed_as_one_argument_without_shell_evaluation(self):
        check = {"exited": True, "exitcode": 0}
        with patch.object(desktop, "ensure_guest_runtime", return_value={}), patch.object(desktop.computer, "acquire_agent"), patch.object(desktop.computer, "release_control"), patch.object(desktop.computer, "guest_exec", side_effect=[check, check]) as guest, patch.object(desktop.computer, "touch_activity"), patch.object(desktop.computer, "status", return_value={}):
            desktop.desktop_type("hello; rm -rf /", "agent:agt_sales:main")
        argv = guest.call_args_list[1].args[0]
        self.assertEqual(argv[-1], "hello; rm -rf /")
        self.assertNotIn("/bin/bash", argv)

    def test_unsupported_key_is_rejected_before_input(self):
        with self.assertRaises(ValueError):
            desktop.desktop_key("ctrl+alt+delete", "agent:agt_sales:main")

    def test_missing_xdotool_is_prepared_inside_guest(self):
        missing = {"exited": True, "exitcode": 1}
        installed = {"exited": True, "exitcode": 0}
        with patch.object(desktop.computer, "guest_exec", side_effect=[missing, installed]) as guest:
            desktop._ensure_xdotool()
        install_argv = guest.call_args_list[1].args[0]
        self.assertEqual(install_argv[:2], ["/bin/bash", "-lc"])
        self.assertIn("apt-get install", install_argv[-1])
        self.assertIn("xdotool", install_argv[-1])

    def test_explicit_desktop_control_route_returns_selected_backend_card(self):
        with patch.object(desktop, "desktop_scroll", return_value={"computer_id": "company-default", "state": "IDLE", "backend": "qemu"}) as scroll:
            result = desktop.route_desktop_control("Company Computer control: scroll down 3", "agent:agt_sales:main")
        scroll.assert_called_once_with("down", "agent:agt_sales:main", steps=3)
        self.assertEqual(result["card"]["mode"], "qemu")
        self.assertEqual(result["card"]["computer_id"], "company-default")

    def test_new_control_layer_has_no_legacy_runtime_dependency(self):
        source = open("agentie/core/company_computer_desktop.py", encoding="utf-8").read().lower()
        self.assertNotIn("wsl", source)
        self.assertNotIn("kasmvnc", source)
        self.assertNotIn("xfce", source)
        self.assertIn("xdotool", source)
        self.assertIn("ensure_guest_runtime", source)
        self.assertIn("company_computer_backend", source)


if __name__ == "__main__":
    unittest.main()
