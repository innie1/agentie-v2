import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main
from agentie.core import agent_chat_presence,agent_registry,agent_threads,team_orchestrator


class ConnectedGroupChatRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);root=Path(self.temp.name)
        self.patches=[
            patch.object(agent_registry,'WORKSPACE',root),patch.object(agent_registry,'AGENTS_FILE',root/'agents.json'),
            patch.object(agent_threads,'WORKSPACE',root),patch.object(agent_threads,'THREADS',root/'agent_threads.json'),
            patch.object(team_orchestrator,'WORKSPACE',root),patch.object(team_orchestrator,'TEAM_FILE',root/'team_jobs.json'),
        ]
        for p in self.patches:p.start()
        self.ada=agent_registry.create_agent('Ada','Customer support owner')['agent']
        self.ben=agent_registry.create_agent('Ben','Customer research owner')['agent']

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def test_group_chat_requires_two_real_agents_and_persists_owner_in_same_thread_store(self):
        with self.assertRaisesRegex(ValueError,'at least two'):
            agent_chat_presence.create_group_chat('Ops',[self.ada['id']])
        thread=agent_chat_presence.create_group_chat('Ops',[self.ada['id'],self.ben['id']],self.ada['id'])
        saved=agent_threads.get_thread(thread['id'])
        self.assertEqual(set(saved['participant_ids']),{self.ada['id'],self.ben['id']})
        self.assertEqual(saved['owner_agent_id'],self.ada['id'])
        self.assertEqual(saved['owner_agent_name'],'Ada')

    def test_owner_must_be_participant_and_does_not_grant_delegation(self):
        other=agent_registry.create_agent('Cora','Operations owner')['agent'];thread=agent_chat_presence.create_group_chat('Ops',[self.ada['id'],self.ben['id']])
        with self.assertRaisesRegex(ValueError,'participant'):
            agent_chat_presence.set_thread_owner(thread['id'],other['id'])
        agent_chat_presence.set_thread_owner(thread['id'],self.ada['id']);updated=agent_registry.get_agent(self.ada['id'])
        self.assertFalse(updated['permissions']['delegate'])

    def test_removed_owner_is_cleared_without_deleting_the_chat(self):
        thread=agent_chat_presence.create_group_chat('Ops',[self.ada['id'],self.ben['id']],self.ada['id'])
        agent_threads.remove_agent_from_threads(self.ada['id'])
        card=agent_chat_presence.connected_thread(agent_threads.get_thread(thread['id']))
        self.assertIsNone(card['owner_agent_id']);self.assertIsNone(card['owner_agent_name'])
        self.assertEqual(card['participants'],['Ben']);self.assertEqual(card['id'],thread['id'])

    def test_presence_comes_from_real_thread_linked_team_job(self):
        thread=agent_chat_presence.create_group_chat('Ops',[self.ada['id'],self.ben['id']])
        with patch.object(agent_threads,'start_team_job'):
            row=agent_threads.post_message(thread['id'],'user',None,'User','@Ben investigate the issue')
        job_id=row['metadata']['team_job_id'];job=team_orchestrator.get_team_job(job_id);hid=job['handoffs'][0]['id']
        def working(j):
            next(x for x in j['handoffs'] if x['id']==hid).update(status='working')
            j['status']='working'
        team_orchestrator._mutate(job_id,working)
        card=agent_chat_presence.connected_thread(agent_threads.get_thread(thread['id']))
        ben=next(x for x in card['presence'] if x['agent_name']=='Ben')
        self.assertEqual(ben['status'],'working');self.assertEqual(ben['outstanding_tasks'],1);self.assertEqual(card['working_count'],1)

    def test_actual_platform_route_delivers_connected_chat_ui(self):
        routes=[r for r in main.app.routes if getattr(r,'path',None)=='/platform.js']
        self.assertGreaterEqual(len(routes),1)
        response=asyncio.run(routes[0].endpoint());text=response.body.decode('utf-8')
        self.assertTrue('__agentieNext4UI' in text or '/platform-next4.js' in text)
        layer_routes=[r for r in main.app.routes if getattr(r,'path',None)=='/platform-next4.js']
        self.assertEqual(len(layer_routes),1)
        layer=asyncio.run(layer_routes[0].endpoint()).body.decode('utf-8')
        for marker in ('__agentieNext4UI','/platform/agent-chats','New group chat','n4-agent-pick','Skill Marketplace','/platform/google-events/status'):
            self.assertIn(marker,layer)

    def test_base_platform_loads_connected_layers_even_when_it_is_the_only_platform_route(self):
        text=Path('frontend/platform.js').read_text(encoding='utf-8')
        for marker in ('__agentiePlatformLayerLoader','/platform-automation.js','/platform-permission-guard.js','/platform-next4.js'):
            self.assertIn(marker,text)
        api_source=Path('agentie/core/platform_next4_api.py').read_text(encoding='utf-8')
        self.assertIn('@router.get("/platform-automation.js")',api_source)
        self.assertIn('@router.get("/platform-permission-guard.js")',api_source)
        self.assertIn('@router.get("/platform-next4.js")',api_source)

    def test_next4_group_chat_ui_fetches_real_agents_and_uses_checkboxes_not_participant_prompt(self):
        text=Path('frontend/platform_next4.js').read_text(encoding='utf-8')
        self.assertIn('/platform/agents',text);self.assertIn('/platform/agent-chats',text);self.assertIn('type="checkbox"',text)
        self.assertNotIn("prompt('Participants",text);self.assertNotIn('Participants (comma-separated)',text)
        self.assertIn('Select at least two agents',text);self.assertIn('n4-presence-chip',text)


if __name__=='__main__':unittest.main()
