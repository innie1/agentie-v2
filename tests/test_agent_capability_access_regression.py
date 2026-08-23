import tempfile
import unittest
from pathlib import Path

from agentie.core import agent_registry, mcp_client, agent_access
from agentie.core.agent_access import access_snapshot, mcp_allowed, set_mcp_access, set_skill_access, skill_allowed, set_global_mcp_access, set_global_skill_access


class AgentCapabilityAccessRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        self.old_agents=agent_registry.AGENTS_FILE;self.old_mcp=mcp_client.REGISTRY;self.old_global=agent_access.GLOBAL_ACCESS_FILE
        agent_registry.AGENTS_FILE=root/'agents.json';mcp_client.REGISTRY=root/'mcp_servers.json';agent_access.GLOBAL_ACCESS_FILE=root/'capability_access.json'
        self.agent=agent_registry.create_agent('Alex','CTO','coding')['agent']
        mcp_client.add_local_server('filesystem','npx -y @modelcontextprotocol/server-filesystem workspace')
    def tearDown(self):
        agent_registry.AGENTS_FILE=self.old_agents;mcp_client.REGISTRY=self.old_mcp;agent_access.GLOBAL_ACCESS_FILE=self.old_global;self.temp.cleanup()

    def test_new_agents_use_shared_workspace_capability_mode(self):
        agent=agent_registry.get_agent('Alex');self.assertEqual(agent['permissions']['capability_mode'],'shared')
        self.assertTrue(skill_allowed(agent,'code-execution'))
        snap=access_snapshot(agent['id']);item=next(x for x in snap['skills'] if x['id']=='code-execution')
        self.assertEqual(snap['capability_mode'],'shared');self.assertTrue(item['inherited']);self.assertEqual(item['mode'],'shared');self.assertTrue(item['effective'])

    def test_per_agent_tool_grants_are_removed(self):
        with self.assertRaisesRegex(ValueError,'Per-agent tool access has been removed'):
            set_skill_access(self.agent['id'],'code-execution','block')
        with self.assertRaisesRegex(ValueError,'Per-agent tool access has been removed'):
            set_mcp_access(self.agent['id'],'filesystem',False)
        self.assertTrue(skill_allowed(agent_registry.get_agent('Alex'),'code-execution'))
        self.assertTrue(mcp_allowed(agent_registry.get_agent('Alex'),'filesystem'))

    def test_workspace_skill_toggle_applies_to_existing_and_future_agents(self):
        set_global_skill_access('code-execution',False);self.assertFalse(skill_allowed(agent_registry.get_agent('Alex'),'code-execution'))
        mira=agent_registry.create_agent('Mira','Anything')['agent'];self.assertFalse(skill_allowed(mira,'code-execution'))
        set_global_skill_access('code-execution',True);self.assertTrue(skill_allowed(agent_registry.get_agent('Alex'),'code-execution'));self.assertTrue(skill_allowed(mira,'code-execution'))

    def test_connected_mcp_is_shared_and_workspace_toggle_applies_to_all_agents(self):
        self.assertTrue(mcp_allowed(agent_registry.get_agent('Alex'),'filesystem'))
        set_global_mcp_access('filesystem',False);self.assertFalse(mcp_allowed(agent_registry.get_agent('Alex'),'filesystem'))
        mira=agent_registry.create_agent('Mira','critic','research')['agent'];self.assertFalse(mcp_allowed(mira,'filesystem'))
        set_global_mcp_access('filesystem',True);self.assertTrue(mcp_allowed(agent_registry.get_agent('Alex'),'filesystem'));self.assertTrue(mcp_allowed(mira,'filesystem'))

    def test_tool_selection_no_longer_creates_agent_level_approval_gate(self):
        self.assertIsNone(agent_access.guard_agent_capability(f"agent:{self.agent['id']}:main",'Use filesystem to inspect the project'))
        source=Path('agentie/core/agent_access.py').read_text(encoding='utf-8')
        self.assertIn('Approval is attached to consequential actions',source)
        self.assertIn('return None',source.split('def guard_agent_capability',1)[1])

    def test_plugins_ui_blocks_old_per_agent_editor_and_explains_shared_tools(self):
        loader=Path('frontend/create_menu_loader.js').read_text(encoding='utf-8')
        self.assertIn('Shared workspace tools',loader)
        self.assertIn('agentie-shared-access-sentinel',loader)
        self.assertIn(".agent-access-box:not(.agentie-shared-access-sentinel)",loader)
        self.assertIn('Connected tools and enabled capabilities are available to every agent automatically',loader)


if __name__=='__main__':unittest.main()
