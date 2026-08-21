import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import agent_registry, role_store


class AgentPinningRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        self.patches=[
            patch.object(agent_registry,"WORKSPACE",root),
            patch.object(agent_registry,"AGENTS_FILE",root/"agents.json"),
        ]
        for p in self.patches:p.start()

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()

    def test_pinned_agents_stay_above_unpinned_agents(self):
        alex=agent_registry.create_agent("Alex","CTO","manager")["agent"]
        mira=agent_registry.create_agent("Mira","critic","research")["agent"]
        agent_registry.set_agent_pinned(mira["id"],True)
        names=[x["name"] for x in agent_registry.list_agents()]
        self.assertEqual(names,["Mira","Alex"])

    def test_new_agents_are_created_below_existing_pins(self):
        mira=agent_registry.create_agent("Mira","critic","research")["agent"]
        agent_registry.set_agent_pinned(mira["id"],True)
        agent_registry.create_agent("Vera","verifier","research")
        agent_registry.create_agent("Coder","coder","coding")
        names=[x["name"] for x in agent_registry.list_agents()]
        self.assertEqual(names[0],"Mira")
        self.assertEqual(names[1:],["Vera","Coder"])

    def test_multiple_pins_keep_stable_pin_order(self):
        alex=agent_registry.create_agent("Alex","CTO","manager")["agent"]
        mira=agent_registry.create_agent("Mira","critic","research")["agent"]
        vera=agent_registry.create_agent("Vera","verifier","research")["agent"]
        agent_registry.set_agent_pinned(mira["id"],True)
        agent_registry.set_agent_pinned(alex["id"],True)
        names=[x["name"] for x in agent_registry.list_agents()]
        self.assertEqual(names,["Mira","Alex","Vera"])

    def test_unpin_returns_agent_to_normal_group(self):
        alex=agent_registry.create_agent("Alex","CTO","manager")["agent"]
        mira=agent_registry.create_agent("Mira","critic","research")["agent"]
        agent_registry.set_agent_pinned(mira["id"],True)
        agent_registry.set_agent_pinned(mira["id"],False)
        items=agent_registry.list_agents()
        self.assertFalse(next(x for x in items if x["id"]==mira["id"])["pinned"])
        self.assertEqual([x["name"] for x in items],["Alex","Mira"])

    def test_chat_commands_pin_and_unpin(self):
        mira=agent_registry.create_agent("Mira","critic","research")["agent"]
        pinned=role_store.route_role_command("Pin agent Mira")
        self.assertIn("pinned to the top",pinned["message"])
        self.assertTrue(agent_registry.get_agent(mira["id"])["pinned"])
        unpinned=role_store.route_role_command("Unpin Mira")
        self.assertIn("unpinned",unpinned["message"])
        self.assertFalse(agent_registry.get_agent(mira["id"])["pinned"])


if __name__=="__main__":unittest.main()
