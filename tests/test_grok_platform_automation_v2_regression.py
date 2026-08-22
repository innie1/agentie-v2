import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch

from agentie.core import (
    agent_access,
    agent_builder,
    agent_prompt,
    agent_registry,
    agent_threads,
    automation_events,
    external_triggers,
    failure_recovery,
    file_service,
    mcp_client,
    platform_router,
    routine_engine,
    routine_worker,
    skill_library,
    skill_registry,
    team_orchestrator,
    whatsapp_webhook,
    workflow_skills,
)
from agentie.tools import approval_tools,persistent_tools


class GrokPlatformAutomationV2RegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);self.root=Path(self.temp.name);skills=self.root/'skills'
        self.patches=[
            patch.object(agent_registry,'WORKSPACE',self.root),patch.object(agent_registry,'AGENTS_FILE',self.root/'agents.json'),
            patch.object(agent_access,'GLOBAL_ACCESS_FILE',self.root/'capability_access.json'),
            patch.object(agent_prompt,'WORKSPACE',self.root),patch.object(agent_prompt,'PROMPTS_FILE',self.root/'agent_instruction_profiles.json'),
            patch.object(skill_registry,'WORKSPACE',self.root),patch.object(skill_registry,'SKILLS_DIR',skills),patch.object(skill_registry,'STATE',self.root/'skills_state.json'),
            patch.object(workflow_skills,'WORKSPACE',self.root),patch.object(workflow_skills,'SKILLS_DIR',skills),
            patch.object(automation_events,'WORKSPACE',self.root),patch.object(automation_events,'EVENTS',self.root/'automation_events.json'),
            patch.object(file_service,'WORKSPACE',self.root),patch.object(file_service,'UPLOADS',self.root/'uploads'),patch.object(file_service,'EXTRACTED',self.root/'extracted'),
            patch.object(agent_threads,'WORKSPACE',self.root),patch.object(agent_threads,'THREADS',self.root/'agent_threads.json'),
            patch.object(team_orchestrator,'WORKSPACE',self.root),patch.object(team_orchestrator,'TEAM_FILE',self.root/'team_jobs.json'),
            patch.object(routine_engine,'WORKSPACE',self.root),patch.object(routine_engine,'ROUTINES',self.root/'routines.json'),patch.object(routine_engine,'RUNS',self.root/'routine_runs.json'),
            patch.object(routine_worker,'WORKSPACE',self.root),patch.object(routine_worker,'EVENTS',self.root/'routine_events.json'),
            patch.object(mcp_client,'REGISTRY',self.root/'mcp_servers.json'),patch.object(approval_tools,'STORE',self.root/'approvals.json'),
        ]
        for p in self.patches:p.start()

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def test_external_event_normalization_security_and_dedupe(self):
        self.assertEqual(external_triggers.normalize_event_type('Incoming email'),'email.received')
        self.assertEqual(external_triggers.normalize_event_type('CRM Lead Created'),'crm.lead.created')
        with patch.dict(os.environ,{},clear=True):
            self.assertTrue(external_triggers.webhook_allowed('127.0.0.1',None));self.assertFalse(external_triggers.webhook_allowed('192.168.1.20',None))
        with patch.dict(os.environ,{'AGENTIE_AUTOMATION_WEBHOOK_TOKEN':'abc'},clear=False):
            self.assertTrue(external_triggers.webhook_allowed('192.168.1.20','abc'));self.assertFalse(external_triggers.webhook_allowed('127.0.0.1','wrong'))
        first=external_triggers.publish_external_event('crm.lead.created',{'id':'lead1'},source='crm',external_id='lead1');second=external_triggers.publish_external_event('crm.lead.created',{'id':'lead1'},source='crm',external_id='lead1')
        self.assertEqual(first['id'],second['id']);self.assertEqual(len(automation_events.recent_events()),1)

    def test_file_upload_emits_real_file_event(self):
        card=file_service.save_upload('brief.txt',b'hello')
        event=automation_events.recent_events()[0]
        self.assertEqual(event['type'],'file.uploaded');self.assertEqual(event['payload']['name'],card['name']);self.assertEqual(len(event['payload']['sha256']),64)

    def test_whatsapp_payload_publishes_message_event_without_faking_connection(self):
        payload={'entry':[{'changes':[{'value':{'messages':[{'id':'wamid.1','from':'234800','type':'text','text':{'body':'Hello'}}]}}]}]}
        count=whatsapp_webhook._publish_whatsapp_events(payload);event=automation_events.recent_events()[0]
        self.assertEqual(count,1);self.assertEqual(event['type'],'whatsapp.message.received');self.assertEqual(event['payload']['body'],'Hello');self.assertEqual(event['payload']['from'],'234800')

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

    def test_skill_library_installs_draft_duplicates_and_assigns_explicitly(self):
        agent=agent_registry.create_agent('Ada','Research owner')['agent'];installed=skill_library.install_template('competitor-research')
        self.assertEqual(installed['status'],'draft');self.assertEqual(skill_library.install_template('competitor-research')['id'],installed['id'])
        copy=skill_library.duplicate_skill(installed['id'],'Competitor Research Copy');self.assertEqual(copy['status'],'draft');self.assertIsNone(copy.get('source_workflow_id'))
        skill_library.assign_skill(installed['id'],agent['id']);updated=agent_registry.get_agent(agent['id']);self.assertIn(installed['id'],updated['skills'])
        library=skill_library.list_library();self.assertTrue(any(x['id']=='competitor-research' and x['installed'] for x in library['templates']))

    def test_builder_recommendations_are_not_grants_until_explicitly_selected(self):
        draft={'name':'Ada','job':'Support owner','skills':[{'id':'research','score':5}], 'plugins':[{'id':'gmail','score':5}], 'responsibilities':[]}
        normalized=agent_builder.normalize_create_spec(draft);self.assertEqual(normalized['skills'],[]);self.assertEqual(normalized['plugins'],[])
        explicit=agent_builder.normalize_create_spec({**draft,'skills':['research'],'plugins':['gmail']});self.assertEqual(explicit['skills'],['research']);self.assertEqual(explicit['plugins'],['gmail'])
        selected=agent_builder.normalize_create_spec({**draft,'skills':[{'id':'research','selected':True}],'plugins':[{'id':'gmail','selected':True}]});self.assertEqual(selected['skills'],['research']);self.assertEqual(selected['plugins'],['gmail'])

    def test_generated_prompt_does_not_authorize_handoff_without_delegate_permission(self):
        plain=agent_registry.create_agent('Ada','Support lead')['agent'];manager=agent_registry.create_agent('Cora','Support lead',permissions={'delegate':True})['agent']
        p=agent_prompt.build_agent_instructions(plain);m=agent_prompt.build_agent_instructions(manager)
        self.assertIn('do not independently delegate or hand off work',p);self.assertNotIn('You are allowed to coordinate and delegate work',p)
        self.assertIn('You are allowed to coordinate and delegate work',m)

    def test_chat_reply_persists_parent_and_reaction_toggles_with_events(self):
        ada=agent_registry.create_agent('Ada','Support owner')['agent'];thread=agent_threads.create_thread('Support',[ada['id']]);origin=agent_threads.post_message(thread['id'],'user',None,'User','Question');reply=agent_threads.reply_to_message(thread['id'],origin['id'],'Follow-up')
        self.assertEqual(reply['metadata']['reply_to_message_id'],origin['id'])
        agent_threads.react_to_message(thread['id'],origin['id'],'👍');current=agent_threads.get_thread(thread['id']);self.assertEqual(len(current['messages'][0]['reactions']),1)
        agent_threads.react_to_message(thread['id'],origin['id'],'👍');current=agent_threads.get_thread(thread['id']);self.assertEqual(current['messages'][0]['reactions'],[])
        kinds=[x['type'] for x in automation_events.recent_events()];self.assertIn('agent_thread.message',kinds);self.assertIn('agent_thread.reaction',kinds)

    def test_reply_with_mentions_reuses_real_team_job_engine(self):
        ada=agent_registry.create_agent('Ada','Support owner')['agent'];ben=agent_registry.create_agent('Ben','Follow-up owner')['agent'];thread=agent_threads.create_thread('Support',[ada['id'],ben['id']]);origin=agent_threads.post_message(thread['id'],'user',None,'User','Question')
        with patch.object(agent_threads,'start_team_job') as start:
            reply=agent_threads.reply_to_message(thread['id'],origin['id'],'@Ben investigate this')
        self.assertTrue((reply.get('metadata') or {}).get('team_job_id'));start.assert_called_once();self.assertEqual(len(team_orchestrator.list_team_jobs()),1)

    def test_failure_policy_never_bypasses_approval_or_missing_input(self):
        approval=failure_recovery.recovery_policy('approval required before sending',1);missing=failure_recovery.recovery_policy('missing input: customer id',1);transient=failure_recovery.recovery_policy('temporary network timeout',1)
        self.assertEqual(approval['action'],'ask_user');self.assertFalse(approval['automatic']);self.assertEqual(missing['action'],'ask_user');self.assertFalse(missing['automatic']);self.assertEqual(transient['action'],'replan');self.assertTrue(transient['automatic'])

    def test_failed_autopilot_handoff_reassigns_bounded_context_and_can_finish_recovered(self):
        manager=agent_registry.create_agent('Cora','Coordinator',permissions={'delegate':True})['agent'];failed=agent_registry.create_agent('Ada','Customer issue investigator')['agent'];alternate=agent_registry.create_agent('Ben','Customer issue investigator and reviewer')['agent'];job=team_orchestrator.create_team_job('investigate customer issue',[failed],requested_by=manager['id']);hid=job['handoffs'][0]['id']
        def fail(j):
            j.update(status='failed',autopilot=True,autopilot_manager_id=manager['id'],autopilot_recovery_enabled=True,autopilot_recovery_finalized=False);h=j['handoffs'][0];h.update(status='failed',error='temporary network timeout',attempts=1);h['context'].update({'scoped_brief':'bounded facts','private_memory':'DO NOT COPY','conversation':'DO NOT COPY'})
        team_orchestrator._mutate(job['id'],fail)
        with patch.object(failure_recovery,'rank_agents',return_value=[{'agent':manager,'score':.9},{'agent':alternate,'score':.8}]):decision=failure_recovery.replan_failed_handoff(job['id'],hid)
        self.assertEqual(decision['action'],'reassigned');self.assertEqual(decision['agent']['id'],alternate['id']);ctx=decision['handoff']['context'];self.assertEqual(ctx['scoped_brief'],'bounded facts');self.assertNotIn('private_memory',ctx);self.assertNotIn('conversation',ctx)
        rid=decision['handoff']['id'];team_orchestrator._mutate(job['id'],lambda j:next(x for x in j['handoffs'] if x['id']==rid).update(status='completed',result='recovered result',error=None));final=failure_recovery.finalize_recovery(job['id'],hid,rid)
        original=next(x for x in final['handoffs'] if x['id']==hid);self.assertEqual(original['status'],'recovered');self.assertEqual(final['status'],'completed')

    def test_autopilot_worker_failure_is_not_announced_as_final_failure_before_recovery(self):
        agent=agent_registry.create_agent('Ada','Worker')['agent'];job=team_orchestrator.create_team_job('bounded task',[agent]);hid=job['handoffs'][0]['id']
        def fail(j):j.update(status='failed',autopilot=True,autopilot_recovery_enabled=True,autopilot_recovery_finalized=False);j['handoffs'][0].update(status='failed',error='timeout')
        current=team_orchestrator._mutate(job['id'],fail);team_orchestrator._publish_terminal_event(current)
        kinds=[x['type'] for x in automation_events.recent_events()];self.assertIn('team_job.worker_failed',kinds);self.assertNotIn('team_job.failed',kinds);self.assertEqual(team_orchestrator.poll_team_completion_events(),[])
        team_orchestrator.publish_team_terminal(job['id']);kinds=[x['type'] for x in automation_events.recent_events()];self.assertIn('team_job.failed',kinds);self.assertEqual(len(team_orchestrator.poll_team_completion_events()),1)

    def test_linked_skill_routine_retries_once_only_when_policy_allows(self):
        skill=workflow_skills.create_workflow_skill(name='Check',steps=['check'],status='active');owner=agent_registry.create_agent('Ada','Checker',skills=[skill['id']])['agent'];routine={'id':'routine1','name':'Check routine','skill_id':skill['id'],'owner_agent_id':owner['id'],'owner_agent_name':owner['name'],'failure_policy':'retry_once','trigger_type':'event'}
        responses=[({'status':'failed','message':'temporary network timeout','card':None},'failed'),({'status':'completed','message':'ok','card':None,'run':{'id':'run2'}},'completed')]
        with patch.object(routine_worker,'_execute_linked_skill_once',new=AsyncMock(side_effect=responses)) as execute:asyncio.run(routine_worker._run_linked_skill(routine))
        self.assertEqual(execute.await_count,2);runs=routine_engine.list_runs(routine_id='routine1');self.assertEqual(runs[0]['status'],'completed');self.assertTrue(runs[0]['retried']);self.assertTrue(any(x['status']=='retrying' for x in runs))

    def test_linked_skill_routine_does_not_retry_approval_failure(self):
        skill=workflow_skills.create_workflow_skill(name='Send',steps=['send'],status='active');owner=agent_registry.create_agent('Ada','Sender',skills=[skill['id']])['agent'];routine={'id':'routine2','name':'Send routine','skill_id':skill['id'],'owner_agent_id':owner['id'],'owner_agent_name':owner['name'],'failure_policy':'retry_once','trigger_type':'event'}
        response=({'status':'failed','message':'approval required before sending','card':None},'failed')
        with patch.object(routine_worker,'_execute_linked_skill_once',new=AsyncMock(return_value=response)) as execute:asyncio.run(routine_worker._run_linked_skill(routine))
        execute.assert_awaited_once();self.assertFalse(routine_engine.list_runs(routine_id='routine2')[0]['retried'])

    def test_plugin_event_arguments_redact_secrets_and_complex_values(self):
        safe=persistent_tools._safe_event_arguments({'password':'secret','api_key':'sk-live','query':'hello','payload':{'x':1}})
        self.assertEqual(safe['password'],'<redacted>');self.assertEqual(safe['api_key'],'<redacted>');self.assertEqual(safe['query'],'hello');self.assertEqual(safe['payload'],'<dict>');self.assertNotIn('secret',str(safe));self.assertNotIn('sk-live',str(safe))

    def test_enhanced_platform_script_contains_real_library_automation_reply_and_reaction_ui(self):
        response=asyncio.run(whatsapp_webhook.enhanced_platform_js());text=response.body.decode('utf-8')
        for marker in ('__agentiePlatformAutomationUI','Skill Library','Automation sources','/automation/triggers/status','/skill-library','/reply','/reaction','__agentieBuilderRecommendationGuard'):
            self.assertIn(marker,text)
        guard=Path('frontend/platform_permission_guard.js').read_text(encoding='utf-8');self.assertIn("[data-option-id]",guard);self.assertIn("checked=false",guard)


if __name__=='__main__':unittest.main()
