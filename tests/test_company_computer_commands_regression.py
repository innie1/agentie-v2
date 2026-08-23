import base64
import unittest
from unittest.mock import patch

from agentie.core import company_computer_commands as commands


def encoded(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


class CompanyComputerCommandsRegressionTests(unittest.TestCase):
    def test_normal_terminal_command_runs_inside_guest_as_agentie(self):
        result = {"exited": True, "exitcode": 0, "out-data": encoded("/home/agentie\n")}
        with patch.object(commands.computer, "acquire_agent") as acquire, patch.object(commands.computer, "release_control") as release, patch.object(commands.computer, "guest_exec", return_value=result) as guest, patch.object(commands, "approval_is_granted", return_value=False):
            response = commands.run_guest_command("pwd", "agent:agt_ops:main")
        acquire.assert_called_once_with("agt_ops")
        release.assert_called_once_with("agt_ops")
        argv = guest.call_args.args[0]
        self.assertIn("/usr/sbin/runuser", argv)
        self.assertIn("agentie", argv)
        self.assertIn("/bin/bash", argv)
        self.assertEqual(argv[-1], "pwd")
        self.assertEqual(response["terminal"]["output"], "/home/agentie\n")
        self.assertEqual(response["terminal"]["user"], "agentie")
        self.assertEqual(response["card"]["mode"], "qemu")

    def test_package_install_requires_existing_approval_before_guest_execution(self):
        with patch.object(commands, "approval_is_granted", return_value=False), patch.object(commands, "create_approval", return_value={"id": "approve1", "status": "pending"}) as create, patch.object(commands.computer, "guest_exec") as guest:
            response = commands.run_guest_command("apt-get install -y inkscape", "agent:agt_ops:main")
        guest.assert_not_called()
        self.assertTrue(response["approval_required"])
        self.assertEqual(response["card"]["type"], "approvals")
        metadata = create.call_args.args[2]
        self.assertEqual(metadata["kind"], "computer_guest_command")
        self.assertTrue(metadata["persistent_change"])
        self.assertEqual(metadata["agent_id"], "agt_ops")

    def test_approved_system_change_runs_as_root_and_consumes_once(self):
        result = {"exited": True, "exitcode": 0, "out-data": encoded("ok")}
        with patch.object(commands, "approval_is_granted", return_value=True), patch.object(commands, "consume_approval") as consume, patch.object(commands.computer, "acquire_agent"), patch.object(commands.computer, "release_control"), patch.object(commands.computer, "guest_exec", return_value=result) as guest:
            response = commands.run_guest_command("apt-get install -y inkscape", "agent:agt_ops:main")
        consume.assert_called_once()
        argv = guest.call_args.args[0]
        self.assertEqual(argv[:2], ["/bin/bash", "-lc"])
        self.assertEqual(response["terminal"]["user"], "root")

    def test_destructive_and_external_write_commands_are_approval_gated(self):
        for command in ("rm -rf /home/agentie/old", "git push origin main"):
            with self.subTest(command=command), patch.object(commands, "approval_is_granted", return_value=False), patch.object(commands, "create_approval", return_value={"id": "approval", "status": "pending"}), patch.object(commands.computer, "guest_exec") as guest:
                response = commands.run_guest_command(command, "agent:agt_ops:main")
            guest.assert_not_called()
            self.assertTrue(response["approval_required"])

    def test_install_package_rejects_shell_injection(self):
        with self.assertRaises(ValueError):
            commands.install_guest_package("curl;rm -rf /", "agent:agt_ops:main")

    def test_natural_run_in_terminal_routes_to_company_computer(self):
        with patch.object(commands, "run_guest_command", return_value={"message": "done", "card": {"type": "desktop_view", "mode": "qemu"}}) as run:
            response = commands.route_company_computer_command("Run pwd in the terminal", "agent:agt_ops:main")
        run.assert_called_once_with("pwd", "agent:agt_ops:main")
        self.assertEqual(response["card"]["mode"], "qemu")

    def test_file_transfer_commands_use_real_qga_file_layer(self):
        upload = {"name": "report.pdf", "guest_path": "/home/agentie/Agentie Inbox/report.pdf"}
        download = {"name": "result.txt", "guest_path": "/home/agentie/Agentie Exports/result.txt"}
        with patch.object(commands, "upload_workspace_file", return_value=upload) as put:
            response = commands.route_company_computer_command("Copy report.pdf to the computer", "agent:agt_ops:main")
        put.assert_called_once_with("report.pdf")
        self.assertEqual(response["card"]["transfer"]["guest_path"], upload["guest_path"])
        with patch.object(commands, "download_guest_file", return_value=download) as get:
            response = commands.route_company_computer_command("Download /home/agentie/Agentie Exports/result.txt from the computer", "agent:agt_ops:main")
        get.assert_called_once()
        self.assertEqual(response["card"]["transfer"]["name"], "result.txt")

    def test_app_launch_occurs_inside_guest_not_host(self):
        result = {"exited": True, "exitcode": 0}
        status = {"computer_id": "company-default", "state": "IDLE", "persistent": True}
        with patch.object(commands.computer, "acquire_agent") as acquire, patch.object(commands.computer, "release_control") as release, patch.object(commands.computer, "guest_exec", return_value=result) as guest, patch.object(commands.computer, "status", return_value=status):
            response = commands.launch_guest_app("terminal", "agent:agt_ops:main")
        acquire.assert_called_once_with("agt_ops")
        release.assert_called_once_with("agt_ops")
        argv = guest.call_args.args[0]
        self.assertIn("/usr/bin/xterm", argv)
        self.assertEqual(response["card"]["mode"], "qemu")


if __name__ == "__main__":
    unittest.main()
