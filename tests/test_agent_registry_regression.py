import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import agent_registry, role_store


class AgentRegistryRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.agents_file = root / "agents.json"
        self.roles_file = root / "agent_roles.json"
        self.patches = [
            patch.object(agent_registry, "AGENTS_FILE", self.agents_file),
            patch.object(role_store, "ROLES", self.roles_file),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_create_agent_has_private_memory_neutral_runtime_and_explicit_permissions(self):
        result = agent_registry.create_agent("Alex", "CTO", "manager")
        agent = result["agent"]
        self.assertTrue(result["created"])
        self.assertTrue(agent["id"].startswith("agt_"))
        self.assertEqual(agent["memory_scope"], f"agent:{agent['id']}")
        self.assertEqual(agent["session_prefix"], f"agent:{agent['id']}:")
        # Passing an old compatibility base must not classify a user-created
        # employee or silently grant delegation authority.
        self.assertEqual(agent["base"], "general")
        self.assertEqual(agent["runtime_profile"], "general")
        self.assertFalse(agent["permissions"]["delegate"])
        self.assertEqual(agent["permissions"].get("capability_mode"), "explicit")

    def test_duplicate_name_reuses_existing_agent(self):
        first = agent_registry.create_agent("Alex", "CTO", "manager")
        second = agent_registry.create_agent("alex", "CTO", "manager")
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["agent"]["id"], second["agent"]["id"])
        self.assertEqual(len(agent_registry.list_agents()), 1)

    def test_conversational_named_agent_creation_is_local_and_not_preclassified(self):
        result = role_store.route_role_command("Create an agent called Alex who is my CTO")
        self.assertIsNotNone(result)
        self.assertEqual(result["card"]["type"], "agent_profile")
        self.assertEqual(result["card"]["name"], "Alex")
        self.assertEqual(result["card"]["role"].lower(), "cto")
        self.assertEqual(result["card"]["base"], "general")
        self.assertFalse(result["card"]["permissions"]["delegate"])
        self.assertEqual(result["card"]["permissions"].get("capability_mode"), "explicit")

    def test_agent_role_creation_with_purpose(self):
        result = role_store.route_role_command("Create a content creator agent for INNIE")
        self.assertIsNotNone(result)
        self.assertEqual(result["card"]["role"].lower(), "content creator")
        self.assertEqual(result["card"]["purpose"], "INNIE")
        self.assertEqual(result["card"]["base"], "general")

    def test_manager_relationship_builds_hierarchy_without_granting_delegate_permission(self):
        ceo = agent_registry.create_agent("CEO", "CEO", "manager")["agent"]
        cto = agent_registry.create_agent("Alex", "CTO", "manager")["agent"]
        updated = agent_registry.update_agent_manager(cto["id"], ceo["id"])
        self.assertEqual(updated["manager_id"], ceo["id"])
        self.assertFalse(ceo["permissions"]["delegate"])
        tree = agent_registry.hierarchy()
        root = next(item for item in tree if item["id"] == ceo["id"])
        self.assertEqual(root["reports"][0]["id"], cto["id"])

    def test_list_agents_command_returns_directory(self):
        agent_registry.create_agent("Alex", "CTO", "manager")
        result = role_store.route_role_command("Show my agents")
        self.assertEqual(result["card"]["type"], "agents")
        self.assertEqual(len(result["card"]["items"]), 1)


if __name__ == "__main__":
    unittest.main()
