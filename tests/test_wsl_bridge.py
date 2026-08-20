import subprocess
import unittest
from unittest.mock import patch

from agentie.core import wsl_bridge


class WslBridgeTests(unittest.TestCase):
    def test_terminal_runs_inside_linux_workspace(self):
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="/home/user/AgentieWorkspace\n", stderr="")
        with patch.object(wsl_bridge, "_run_wsl", return_value=proc) as run:
            result = wsl_bridge.run_terminal("pwd")
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("AgentieWorkspace", result["output"])
        script = run.call_args.args[0]
        self.assertIn("AgentieWorkspace", script)
        self.assertIn("bash -lc", script)

    def test_terminal_blocks_destructive_system_commands(self):
        for command in ("sudo apt update", "rm -rf /", "shutdown now", "mkfs.ext4 /dev/sda"):
            with self.subTest(command=command):
                with self.assertRaises(ValueError):
                    wsl_bridge.run_terminal(command)

    def test_path_cannot_escape_linux_workspace(self):
        for path in ("../secret.txt", "/etc/passwd", "folder/../../secret"):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    wsl_bridge.read_text_file(path)

    def test_list_files_parses_wsl_results(self):
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="d\tproject\t4096\nf\tnotes.txt\t12\n", stderr="")
        with patch.object(wsl_bridge, "_run_wsl", return_value=proc):
            result = wsl_bridge.list_files()
        self.assertEqual(result["workspace"], "~/AgentieWorkspace")
        self.assertEqual(result["items"][0]["kind"], "folder")
        self.assertEqual(result["items"][1]["name"], "notes.txt")
        self.assertEqual(result["items"][1]["size_bytes"], 12)

    def test_read_text_file_returns_linux_content(self):
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="hello from linux", stderr="")
        with patch.object(wsl_bridge, "_run_wsl", return_value=proc):
            result = wsl_bridge.read_text_file("docs/hello.txt")
        self.assertFalse(result["binary"])
        self.assertEqual(result["content"], "hello from linux")

    def test_write_text_file_stays_in_linux_workspace(self):
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="5\n", stderr="")
        with patch.object(wsl_bridge, "_run_wsl", return_value=proc) as run:
            result = wsl_bridge.write_text_file("notes/a.txt", "hello")
        self.assertEqual(result["size_bytes"], 5)
        self.assertIn("AgentieWorkspace", run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
