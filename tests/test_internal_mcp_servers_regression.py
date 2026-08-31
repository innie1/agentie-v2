from __future__ import annotations

import unittest

from mcp import Client

from agentie import (
    mcp_business_data_server,
    mcp_channels_server,
    mcp_company_server,
    mcp_computer_server,
    mcp_workspace_server,
)
from agentie.mcp_business_data_server import _filters, _table
from agentie.mcp_internal_setup import INTERNAL_SERVERS
from agentie.mcp_runtime import approval_action


class InternalMcpServersRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def _tool_names(self, server) -> set[str]:
        async with Client(server, raise_exceptions=True) as client:
            result = await client.list_tools()
        return {tool.name for tool in result.tools}

    async def test_company_mcp_exposes_company_operations(self):
        names = await self._tool_names(mcp_company_server.mcp)
        self.assertTrue(
            {
                "list_company_agents",
                "get_company_agent",
                "list_company_projects",
                "get_company_project",
                "list_company_jobs",
                "get_company_job",
                "list_company_routines",
                "list_company_approvals",
                "create_company_agent",
                "create_company_project",
                "delegate_company_job",
            }.issubset(names)
        )

    async def test_computer_mcp_wraps_existing_company_computer(self):
        names = await self._tool_names(mcp_computer_server.mcp)
        self.assertTrue(
            {
                "get_computer_status",
                "start_company_computer",
                "stop_company_computer",
                "suspend_company_computer",
                "resume_company_computer",
                "run_company_computer_command",
                "open_company_computer_app",
                "copy_workspace_file_to_computer",
                "copy_computer_file_to_workspace",
            }.issubset(names)
        )

    async def test_channels_mcp_exposes_real_telegram_and_whatsapp_surface(self):
        names = await self._tool_names(mcp_channels_server.mcp)
        self.assertTrue(
            {
                "get_channel_status",
                "list_channel_messages",
                "get_channel_message",
                "send_channel_message",
            }.issubset(names)
        )

    async def test_business_data_mcp_has_safe_crud_surface(self):
        names = await self._tool_names(mcp_business_data_server.mcp)
        self.assertTrue(
            {
                "get_business_data_status",
                "query_business_table",
                "insert_business_record",
                "update_business_rows",
                "delete_business_rows",
            }.issubset(names)
        )

    async def test_workspace_mcp_exposes_files_and_company_knowledge(self):
        names = await self._tool_names(mcp_workspace_server.mcp)
        self.assertTrue(
            {
                "list_workspace_uploads",
                "inspect_workspace_file",
                "read_workspace_file_text",
                "preview_workspace_data",
                "checksum_workspace_file",
                "write_workspace_text_file",
                "search_company_knowledge",
                "add_company_knowledge_item",
                "update_company_knowledge_item",
                "delete_company_knowledge_item",
            }.issubset(names)
        )

    def test_internal_setup_registers_all_five_servers(self):
        self.assertEqual(
            set(INTERNAL_SERVERS),
            {
                "agentie-company",
                "agentie-computer",
                "agentie-channels",
                "agentie-business-data",
                "agentie-workspace",
            },
        )

    def test_approval_actions_are_payload_specific_and_stable(self):
        first = approval_action("agentie-company", "create_company_agent", {"name": "Ben"})
        repeat = approval_action("agentie-company", "create_company_agent", {"name": "Ben"})
        other = approval_action("agentie-company", "create_company_agent", {"name": "Ada"})
        self.assertEqual(first, repeat)
        self.assertNotEqual(first, other)
        self.assertTrue(first.startswith("mcp:agentie-company:create_company_agent:"))
        self.assertLess(len(first), 500)

    def test_business_data_rejects_unsafe_table_and_filter_names(self):
        self.assertEqual(_table("orders_2026"), "orders_2026")
        with self.assertRaises(ValueError):
            _table("orders;drop table users")
        self.assertEqual(_filters('{"store_id":"abc"}'), {"store_id": "abc"})
        with self.assertRaises(ValueError):
            _filters('{"store-id":"abc"}')


if __name__ == "__main__":
    unittest.main()
