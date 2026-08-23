import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agentie.core import (
    agent_builder,
    agent_prompt,
    agent_registry,
    agent_threads,
    automation_events,
    external_triggers,
    routine_engine,
    routine_worker,
    skill_library,
    whatsapp_webhook,
)
from agentie.core import platform_router


class GrokPlatformAutomationV2RegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);self.root=Path(self.temp.name)
        self.patches=[
            patch.object(agent_registry,'WORKSPACE',self.root),patch.object(agent_registry,'AGENTS_FILE',self.root/'agents.json'),
            patch.object(agent_prompt,'WORKSPACE',self.root),patch.object(agent_prompt,'PROMPTS_FILE',self.root/'agent_instruction_profiles.json'),
            patch.object(agent_threads,'WORKSPACE',self.root),patch.object(agent_threads,'THREADS',self.root/'agent_threads.json'),
            patch.object(automation_events,'WORKSPACE',self.root),patch.object(automation_events,'EVENTS',self.root/'automation_events.json'),
            patch.object(routine_engine,'WORKSPACE',self.root),patch.object(routine_engine,'ROUTINES',self.root/'routines.json'),patch.object(routine_engine,'RUNS',self.root/'routine_runs.json'),
            patch.object(routine_worker,'WORKSPACE',self.root),patch.object(routine_worker,'EVENTS',self.root/'routine_events.json'),
        ]
        for item in self.patches:item.start()

    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.temp.cleanup()

    def test_platform_router_creates_native_and_generic_external_event_routines(self):
        owner=agent_registry.create_agent('Ada','Operations owner')['agent']
        native=platform_router.route_platform_command('Create a routine called File Review that when a file upload summarize it for agent Ada')
        generic=platform_router.route_platform_command('Create a routine called CRM Follow Up that when webhook crm.lead.created arrives review the lead for agent Ada')
        self.assertEqual(native['card']['event_type'],'file.uploaded');self.assertEqual(generic['card']['event_type'],'crm.lead.created');self.assertEqual(native['card']['owner_agent_id'],owner['id']);self.assertEqual(generic['card']['owner_agent_id'],owner['id'])

    def test_external_event_uses_existing_routine_worker_once(self):
        agent=agent_registry.create_agent('Ada','Operations owner')['agent'];routine,_=routine_engine.create_event_routine(name='Lead review',event_type='crm.lead.created',action='review lead',owner_agent_id=agent['id']);external_triggers.publish_external_event('crm.lead.created',{'id':'1'},source='test',external_id='1')
        with patch.object(routine_worker,'_execute_routine',new=AsyncMock()) as execute:
            asyncio.run(routine_worker._dispatch_internal_events());asyncio.run(routine_worker._dispatch_internal_events())
        execute.assert_awaited_once();self.assertEqual(routine_engine.list_routines(agent['id'])[0]['run_count'],1);self.assertIn(routine['id'],automation_events.recent_events()[0]['delivered_routine_ids'])

    def test_skill_library_installs_draft_duplicates_and_associates_without_permission_grant(self):
        agent=agent_registry.create_agent('Ada','Research owner')['agent'];installed=skill_library.install_template('competitor-research')
        self.assertEqual(installed['status'],'draft');self.assertEqual(skill_library.install_template('competitor-research')['id'],installed['id'])
        copy=skill_library.duplicate_skill(installed['id'],'Competitor Research Copy');self.assertEqual(copy['status'],'draft');self.assertIsNone(copy.get('source_workflow_id'))
        result=skill_library.assign_skill(installed['id'],agent['id']);updated=agent_registry.get_agent(agent['id']);self.assertIn(installed['id'],updated['skills']);self.assertEqual(result['assignment_mode'],'preference');self.assertEqual(updated['permissions']['capability_mode'],'shared')
        library=skill_library.list_library();self.assertTrue(any(x['id']=='competitor-research' and x['installed'] for x in library['templates']))

    def test_builder_recommendations_are_not_per_agent_tool_grants(self):
        draft={'name':'Ada','job':'Support owner','skills':[{'id':'research','score':5}], 'plugins':[{'id':'gmail','score':5}], 'responsibilities':[]}
        normalized=agent_builder.normalize_create_spec(draft);self.assertEqual(normalized['skills'],[]);self.assertEqual(normalized['plugins'],[])
        explicit=agent_builder.normalize_create_spec({**draft,'skills':['research'],'plugins':['gmail']});self.assertEqual(explicit['skills'],['research']);self.assertEqual(explicit['plugins'],['gmail'])
        selected=agent_builder.normalize_create_spec({**draft,'skills':[{'id':'research','selected':True}],'plugins':[{'id':'gmail','selected':True}]});self.assertEqual(selected['skills'],['research']);self.assertEqual(selected['plugins'],['gmail'])
        # Normalization can still preserve older request payloads, but runtime tool
        # access is workspace-shared and does not use these as grants.

    def test_generated_prompt_does_not_authorize_handoff_without_delegate_permission(self):
        plain=agent_registry.create_agent('Ada','Support lead')['agent'];manager=agent_registry.create_agent('Cora','Support lead',permissions={'delegate':True})['agent']
        p=agent_prompt.build_agent_instructions(plain);m=agent_prompt.build_agent_instructions(manager)
        self.assertIn('recommend the better owner',p);self.assertNotIn('may delegate bounded work',p.lower())
        self.assertIn('may delegate bounded work',m.lower())

    def test_chat_reply_persists_parent_and_reaction_toggles_with_events(self):
        ada=agent_registry.create_agent('Ada','Support owner')['agent'];thread=agent_threads.create_thread('Support',[ada['id']]);origin=agent_threads.post_message(thread['id'],'user',None,'User','Question');reply=agent_threads.reply_to_message(thread['id'],origin['id'],'Follow-up')
        self.assertEqual(reply['metadata']['reply_to_message_id'],origin['id'])
        agent_threads.react_to_message(thread['id'],origin['id'],'👍');current=agent_threads.get_thread(thread['id']);self.assertEqual(len(current['messages'][0]['reactions']),1)
        agent_threads.react_to_message(thread['id'],origin['id'],'👍');current=agent_threads.get_thread(thread['id']);self.assertEqual(current['messages'][0]['reactions'],[])
        kinds=[x['type'] for x in automation_events.recent_events()];self.assertIn('agent_thread.message',kinds);self.assertIn('agent_thread.reaction',kinds)

    def test_reply_with_mentions_reuses_real_team_job_engine(self):
        ada=agent_registry.create_agent('Ada','Support owner')['agent'];ben=agent_registry.create_agent('Ben','Follow-up owner')['agent'];thread=agent_threads.create_thread('Support',[ada['id'],ben['id']]);origin=agent_threads.post_message(thread['id'],'user',None,'User','Question')
        with patch.object(agent_threads,'start_team_job') as start:
            reply=agent_threads.reply_to_message(thread['id'],origin['id'],'@Ada @Ben review this')
        self.assertIsNotNone((reply.get('metadata') or {}).get('team_job_id'));start.assert_called_once()

    def test_whatsapp_event_parser_publishes_real_external_event(self):
        payload={'entry':[{'changes':[{'value':{'messages':[{'id':'wamid.1','from':'234800','type':'text','text':{'body':'Hello'}}]}}]}]}
        count=whatsapp_webhook._publish_whatsapp_events(payload);event=automation_events.recent_events()[0]
        self.assertEqual(count,1);self.assertEqual(event['type'],'whatsapp.message.received');self.assertEqual(event['payload']['body'],'Hello');self.assertEqual(event['payload']['from'],'234800')


if __name__=='__main__':unittest.main()
