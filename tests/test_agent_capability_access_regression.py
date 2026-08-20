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

    def test_role_skill_is_real_and_inherited(self):
        agent=agent_registry.get_agent('Alex');self.assertTrue(skill_allowed(agent,'code-execution'))
        snap=access_snapshot(agent['id']);item=next(x for x in snap['skills'] if x['id']=='code-execution')
        self.assertTrue(item['inherited']);self.assertTrue(item['effective'])

    def test_skill_can_be_blocked_and_explicitly_allowed(self):
        set_skill_access(self.agent['id'],'code-execution','block');self.assertFalse(skill_allowed(agent_registry.get_agent('Alex'),'code-execution'))
        set_skill_access(self.agent['id'],'code-execution','allow');self.assertTrue(skill_allowed(agent_registry.get_agent('Alex'),'code-execution'))

    def test_global_mcp_grant_applies_to_existing_and_future_agents(self):
        self.assertFalse(mcp_allowed(agent_registry.get_agent('Alex'),'filesystem'))
        set_global_mcp_access('filesystem',True);self.assertTrue(mcp_allowed(agent_registry.get_agent('Alex'),'filesystem'))
        mira=agent_registry.create_agent('Mira','critic','research')['agent'];self.assertTrue(mcp_allowed(mira,'filesystem'))

    def test_agent_block_overrides_global_mcp_grant(self):
        set_global_mcp_access('filesystem',True);set_mcp_access(self.agent['id'],'filesystem',False)
        self.assertFalse(mcp_allowed(agent_registry.get_agent('Alex'),'filesystem'))
        self.assertEqual(next(x for x in access_snapshot(self.agent['id'])['mcp_servers'] if x['name']=='filesystem')['mode'],'block')

    def test_global_skill_grant_can_be_overridden_by_agent_block(self):
        set_global_skill_access('last30days',True);self.assertTrue(skill_allowed(agent_registry.get_agent('Alex'),'last30days'))
        set_skill_access(self.agent['id'],'last30days','block');self.assertFalse(skill_allowed(agent_registry.get_agent('Alex'),'last30days'))

    def test_runtime_and_ui_are_wired_to_real_access(self):
        main=Path('main.py').read_text(encoding='utf-8');ui=Path('frontend/plugin_access.js').read_text(encoding='utf-8')
        self.assertIn('guard_agent_capability(session_key,request.message)',main)
        self.assertIn('/plugins/agent-access/{agent_id}',main)
        self.assertIn('Always allow for all agents',ui)
        self.assertIn('data-global-skill',ui);self.assertIn('data-global-mcp',ui);self.assertIn('Block',ui)


if __name__=='__main__':unittest.main()
