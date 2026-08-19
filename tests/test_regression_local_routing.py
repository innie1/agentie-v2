import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core.capability_preflight import _allowed_directories_request, _choice, _extension_search, _filename, _folder_name
from agentie.core.capability_router import _looks_filesystem, _native_guarded
from agentie.core.code_execution import route_code_command
from agentie.core.local_router import route_local_actions
from agentie.core.mcp_catalog import presets
from agentie.core.mcp_client import _infer_natural_tool, _mentioned_server, _split_local_command
from agentie.core.reference_router import _direct_timer_create
from agentie.tools import approval_tools


class StableTimerIntentTests(unittest.TestCase):
    def assert_timer(self, text: str, seconds: float) -> None:
        result = _direct_timer_create(text)
        self.assertIsNotNone(result, text)
        self.assertIsInstance(result.get("card"), dict)
        self.assertEqual(result["card"].get("type"), "timer")
        self.assertEqual(float(result["card"].get("duration_seconds")), seconds)

    def test_timer_shorthand_variants(self):
        for text in (
            "timer 10s",
            "timer 10 s",
            "timer for 10 s",
            "a timer for 10 s",
            "set a timer for 10 seconds",
            "start timer 10 sec",
        ):
            with self.subTest(text=text):
                self.assert_timer(text, 10.0)

    def test_timer_reason(self):
        result = _direct_timer_create("timer 20s to check the build")
        self.assertEqual(result["card"].get("reason"), "check the build")


class ExistingLocalBehaviorTests(unittest.TestCase):
    def test_calculation_still_local(self):
        routed = route_local_actions("Calculate 321 * 27")
        self.assertFalse(routed["unresolved"])
        self.assertEqual(routed["results"][0]["card"]["type"], "calculation")
        self.assertEqual(routed["results"][0]["card"]["result"], 8667)

    def test_conversion_still_local(self):
        routed = route_local_actions("Convert 12 kilometers to miles")
        self.assertFalse(routed["unresolved"])
        self.assertIn(routed["results"][0]["card"]["type"], {"conversion", "unit_conversion"})

    def test_time_still_local(self):
        routed = route_local_actions("What time is it")
        self.assertFalse(routed["unresolved"])
        self.assertEqual(routed["results"][0]["card"]["type"], "datetime")

    def test_one_line_python_never_needs_model(self):
        result = route_code_command("Run Python: print(sum(i * i for i in range(1, 101)))")
        self.assertIsNotNone(result)
        self.assertEqual(result["card"]["type"], "multi")
        first = result["card"]["items"][0]["card"]
        self.assertEqual(first["type"], "note")
        self.assertIn("338350", first["content"])


class MCPTransportSafetyTests(unittest.TestCase):
    def test_local_npx_command_parses_without_starting_server(self):
        command, args = _split_local_command("npx -y example-mcp --stdio")
        self.assertIn(command.lower(), {"npx", "npx.cmd"})
        self.assertEqual(args, ["-y", "example-mcp", "--stdio"])

    def test_local_python_command_parses(self):
        command, args = _split_local_command('python "server.py" --stdio')
        self.assertIn(command.lower(), {"python", "python.exe"})
        self.assertEqual(args, ["server.py", "--stdio"])

    def test_windows_cmd_npx_wrapper_is_allowed(self):
        command, args = _split_local_command("cmd /c npx -y example-mcp")
        self.assertIn(command.lower(), {"cmd", "cmd.exe"})
        self.assertEqual(args[:2], ["/c", "npx"])

    def test_arbitrary_shell_is_not_accepted(self):
        with self.assertRaises(ValueError):
            _split_local_command("powershell -Command whoami")
        with self.assertRaises(ValueError):
            _split_local_command("cmd /c whoami")


class MCPNaturalLanguageTests(unittest.TestCase):
    def setUp(self):
        self.server = {
            "name": "filesystem",
            "transport": "stdio",
            "command": "cmd",
            "args": ["/c", "npx", "-y", "@modelcontextprotocol/server-filesystem", r"C:\Users\user\agentie-v2\workspace"],
        }
        self.info = {
            "tools": [
                {"name": "list_directory", "title": "List Directory"},
                {"name": "list_allowed_directories", "title": "List Allowed Directories"},
                {"name": "read_text_file", "title": "Read Text File"},
                {"name": "get_file_info", "title": "Get File Info"},
            ]
        }

    def test_natural_workspace_listing_maps_to_list_directory(self):
        tool, arguments = _infer_natural_tool(
            "Show me the files in my workspace using the filesystem plugin",
            self.server,
            self.info,
        )
        self.assertEqual(tool, "list_directory")
        self.assertEqual(arguments["path"], r"C:\Users\user\agentie-v2\workspace")

    def test_allowed_directory_question_needs_no_arguments(self):
        tool, arguments = _infer_natural_tool(
            "What directories can the filesystem plugin access?",
            self.server,
            self.info,
        )
        self.assertEqual(tool, "list_allowed_directories")
        self.assertEqual(arguments, {})

    def test_direct_plugin_name_is_recognized_without_using_or_with(self):
        with patch("agentie.core.mcp_client.list_servers", return_value=[self.server]):
            self.assertEqual(
                _mentioned_server("What directories can the filesystem plugin access?"),
                "filesystem",
            )


class CapabilityRoutingRegressionTests(unittest.TestCase):
    def test_unnamed_filesystem_request_is_detected(self):
        self.assertTrue(_looks_filesystem("Look at the files in C:\\Users\\user\\agentie-v2\\workspace"))
        self.assertTrue(_looks_filesystem("Show me the files in this workspace"))

    def test_native_intents_are_protected_from_external_auto_routing(self):
        for text in (
            "timer 10s",
            "Remind me in 5 minutes to check the build",
            "Calculate 12 * 8",
            "Convert 5 km to mi",
            "Run Python: print(1 + 1)",
            "What time is it",
            "Remember that my project is Blue Falcon",
        ):
            with self.subTest(text=text):
                self.assertTrue(_native_guarded(text))

    def test_curated_mcp_presets_are_available(self):
        ids = {item["id"] for item in presets()}
        self.assertTrue({"memory", "sequential-thinking", "everything", "fetch", "time-mcp", "git"}.issubset(ids))


class CapabilityPreflightRegressionTests(unittest.TestCase):
    def setUp(self):
        self.server = {
            "name": "filesystem",
            "transport": "stdio",
            "command": "cmd",
            "args": ["/c", "npx", "-y", "@modelcontextprotocol/server-filesystem", r"C:\Users\user\agentie-v2\workspace"],
        }
        self.info = {
            "tools": [
                {"name": "search_files"},
                {"name": "read_text_file"},
                {"name": "get_file_info"},
                {"name": "list_allowed_directories"},
                {"name": "write_file"},
                {"name": "create_directory"},
            ]
        }

    def test_pdf_search_uses_search_files_pattern(self):
        self.assertEqual(_extension_search("Find all PDF files in this workspace."), "*.pdf")
        tool, arguments = _choice("Find all PDF files in this workspace.", self.server, self.info)
        self.assertEqual(tool, "search_files")
        self.assertEqual(arguments["pattern"], "*.pdf")

    def test_read_filename_is_not_confused_with_native_task_tracker(self):
        self.assertEqual(_filename("Read tasks.json."), "tasks.json")
        tool, arguments = _choice("Read tasks.json.", self.server, self.info)
        self.assertEqual(tool, "read_text_file")
        self.assertTrue(arguments["path"].endswith("tasks.json"))

    def test_file_info_filename_maps_to_get_file_info(self):
        tool, arguments = _choice("Show me information about tasks.json.", self.server, self.info)
        self.assertEqual(tool, "get_file_info")
        self.assertTrue(arguments["path"].endswith("tasks.json"))

    def test_generic_allowed_directory_question_is_recognized(self):
        self.assertTrue(_allowed_directories_request("What directories can I access?"))
        tool, arguments = _choice("What directories can I access?", self.server, self.info)
        self.assertEqual(tool, "list_allowed_directories")
        self.assertEqual(arguments, {})

    def test_another_file_called_extracts_only_filename(self):
        text = "Create another file called persistent-test-2.txt in the workspace containing second test."
        self.assertEqual(_filename(text), "persistent-test-2.txt")
        tool, arguments = _choice(text, self.server, self.info)
        self.assertEqual(tool, "write_file")
        self.assertTrue(arguments["path"].endswith("persistent-test-2.txt"))

    def test_create_folder_maps_to_create_directory(self):
        text = "Create a folder called approval-folder in the workspace."
        self.assertEqual(_folder_name(text), "approval-folder")
        tool, arguments = _choice(text, self.server, self.info)
        self.assertEqual(tool, "create_directory")
        self.assertTrue(arguments["path"].endswith("approval-folder"))


class MCPApprovalPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store_patch = patch.object(approval_tools, "STORE", Path(self.temp.name) / "approvals.json")
        self.store_patch.start()

    def tearDown(self):
        self.store_patch.stop()
        self.temp.cleanup()

    def test_read_only_mcp_tools_auto_run(self):
        for tool in ("read_text_file", "list_directory", "search_files", "get_file_info", "directory_tree"):
            with self.subTest(tool=tool):
                self.assertTrue(approval_tools.mcp_tool_is_read_only(tool))
                self.assertTrue(approval_tools.approval_is_granted(f"mcp:filesystem:{tool}:{{}}"))
        self.assertFalse(approval_tools.mcp_tool_is_read_only("write_file"))
        self.assertFalse(approval_tools.approval_is_granted("mcp:filesystem:write_file:{}"))

    def test_approve_once_is_consumed(self):
        action = 'mcp:filesystem:write_file:{"path":"a.txt"}'
        item = approval_tools.create_approval(action, "test")
        approval_tools.resolve_approval(item["id"], True)
        self.assertTrue(approval_tools.approval_is_granted(action))
        self.assertFalse(approval_tools.approval_is_granted(action))

    def test_always_allow_is_scoped_to_server_and_tool(self):
        action = 'mcp:filesystem:write_file:{"path":"a.txt"}'
        item = approval_tools.create_approval(action, "test")
        approval_tools.resolve_approval(item["id"] + ":always", True)
        self.assertTrue(approval_tools.approval_is_granted('mcp:filesystem:write_file:{"path":"b.txt"}'))
        self.assertFalse(approval_tools.approval_is_granted('mcp:filesystem:edit_file:{"path":"b.txt"}'))
        self.assertFalse(approval_tools.approval_is_granted('mcp:other:write_file:{"path":"b.txt"}'))


if __name__ == "__main__":
    unittest.main()
