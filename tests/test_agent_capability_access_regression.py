import tempfile
import unittest
from pathlib import Path

from agentie.core import agent_registry, mcp_client
from agentie.core.agent_access import access_snapshot, mcp_allowed, set_mcp_access, set_skill_access, skill_allowed


class AgentCapabilityAccessRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        self.old_agents=agent_registry.AGENTS_FILE;self.old_mcp=mcp_client.REGISTRY
        agent_registry.AGENTS_FILE=root/'agents.json';mcp_client.REGISTRY=root/'mcp_servers.json'
        self.agent=agent_registry.create_agent('Alex','CTO','coding')['agent']
        mcp_client.add_local_server('filesystem','npx -y @modelcontextprotocol/server-filesystem workspace')
    def tearDown(self):
        agent_registry.AGENTS_FILE=self.old_agents;mcp_client.REGISTRY=self.old_mcp;self.temp.cleanup()

    def test_role_skill_is_real_and_inherited(self):
        agent=agent_registry.get_agent('Alex');self.assertTrue(skill_allowed(agent,'code-execution'))
        snap=access_snapshot(agent['id']);item=next(x for x in snap['skills'] if x['id']=='code-execution')
        self.assertTrue(item['inherited']);self.assertTrue(item['effective'])

    def test_skill_can_be_blocked_and_explicitly_allowed(self):
        set_skill_access(self.agent['id'],'code-execution','block');self.assertFalse(skill_allowed(agent_registry.get_agent('Alex'),'code-execution'))
        set_skill_access(self.agent['id'],'code-execution','allow');self.assertTrue(skill_allowed(agent_registry.get_agent('Alex'),'code-execution'))

    def test_mcp_access_is_per_agent_and_persistent(self):
        agent=agent_registry.get_agent('Alex');self.assertFalse(mcp_allowed(agent,'filesystem'))
        set_mcp_access(agent['id'],'filesystem',True);self.assertTrue(mcp_allowed(agent_registry.get_agent('Alex'),'filesystem'))
        snap=access_snapshot(agent['id']);self.assertTrue(next(x for x in snap['mcp_servers'] if x['name']=='filesystem')['allowed'])

    def test_runtime_and_ui_are_wired_to_real_access(self):
        main=Path('main.py').read_text(encoding='utf-8');ui=Path('frontend/plugin_access.js').read_text(encoding='utf-8')
        self.assertIn('guard_agent_capability(session_key,request.message)',main)
        self.assertIn('/plugins/agent-access/{agent_id}',main)
        self.assertIn('agent_capability_approval',ui)
        self.assertIn('Always allow',ui)
        self.assertIn("kind:'mcp'",ui)


if __name__=='__main__':unittest.main()
