import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main
from agentie.core import agent_prompt,agent_registry,role_store


class PlatformPermissionContractRegressionTests(unittest.TestCase):
    def test_platform_route_serves_enhanced_platform_contract(self):
        routes=[r for r in main.app.routes if getattr(r,'path',None)=='/platform.js']
        self.assertGreaterEqual(len(routes),1)
        # Do not require duplicate FastAPI handlers for the same URL. The stable
        # contract is that Agentie's platform route exists and the enhanced
        # automation/library/chat layer is wired into the loaded platform UI.
        source=Path('agentie/core/whatsapp_webhook.py').read_text(encoding='utf-8')
        extra=Path('frontend/platform_automation.js').read_text(encoding='utf-8')
        base=Path('frontend/platform.js').read_text(encoding='utf-8')
        self.assertIn('enhanced_platform_js',source)
        self.assertIn('platform_automation.js',source)
        self.assertIn('Skill Library',extra)
        self.assertIn('Automation',extra)
        self.assertIn('Agent chats',base)

    def test_chat_creation_recommends_but_does_not_silently_grant_capabilities(self):
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw)
            with patch.object(agent_registry,'WORKSPACE',root),patch.object(agent_registry,'AGENTS_FILE',root/'agents.json'),patch.object(agent_prompt,'WORKSPACE',root),patch.object(agent_prompt,'PROMPTS_FILE',root/'agent_instruction_profiles.json'):
                draft={
                    'name':'Ada','job':'Support owner','description':'Handle customer email','goal':'Help customers','working_style':'Clear','responsibilities':['Handle support'],
                    'instructions':'Own support work','skills':[{'id':'email','name':'Email','score':10}], 'plugins':[{'id':'gmail','name':'Gmail','score':10}],
                    'approval_policy':{},'memory_policy':{},'can_delegate':False,'manager_id':None,
                }
                with patch.object(role_store,'draft_agent_spec',return_value=draft):result=role_store._create_from_spec('Ada','Support owner','Handle customer email')
                agent=result['agent'];self.assertEqual(agent['skills'],[]);self.assertEqual(agent['permissions']['mcp_servers'],[]);self.assertEqual(agent['permissions']['capability_mode'],'explicit')


if __name__=='__main__':unittest.main()
