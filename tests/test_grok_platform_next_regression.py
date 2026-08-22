import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import (
    agent_access,
    agent_lifecycle,
    agent_prompt,
    agent_registry,
    agent_teams,
    agent_threads,
    automation_events,
    capability_planner,
    file_service,
    platform_router,
    routine_engine,
    skill_portability,
    team_orchestrator,
    workflow_skills,
)


class GrokPlatformNextRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);self.root=Path(self.temp.name);skills=self.root/'skills'
        self.patches=[
            patch.object(agent_registry,'WORKSPACE',self.root),patch.object(agent_registry,'AGENTS_FILE',self.root/'agents.json'),
            patch.object(agent_prompt,'WORKSPACE',self.root),patch.object(agent_prompt,'PROMPTS_FILE',self.root/'agent_instruction_profiles.json'),
            patch.object(agent_access,'GLOBAL_ACCESS_FILE',self.root/'capability_access.json'),
            patch.object(agent_teams,'WORKSPACE',self.root),patch.object(agent_teams,'TEAMS',self.root/'agent_teams.json'),
            patch.object(agent_threads,'WORKSPACE',self.root),patch.object(agent_threads,'THREADS',self.root/'agent_threads.json'),
            patch.object(team_orchestrator,'WORKSPACE',self.root),patch.object(team_orchestrator,'TEAM_FILE',self.root/'team_jobs.json'),
            patch.object(routine_engine,'WORKSPACE',self.root),patch.object(routine_engine,'ROUTINES',self.root/'routines.json'),patch.object(routine_engine,'RUNS',self.root/'routine_runs.json'),
            patch.object(automation_events,'WORKSPACE',self.root),patch.object(automation_events,'EVENTS',self.root/'automation_events.json'),
            patch.object(workflow_skills,'WORKSPACE',self.root),patch.object(workflow_skills,'SKILLS_DIR',skills),
            patch.object(file_service,'WORKSPACE',self.root),patch.object(file_service,'UPLOADS',self.root/'uploads'),patch.object(file_service,'EXTRACTED',self.root/'extracted'),
        ]
        for item in self.patches:item.start()

    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.temp.cleanup()

    def test_duplicate_agent_copies_configuration_and_routines_but_not_learned_context(self):
        source=agent_registry.create_agent('Ada','Customer operations owner',skills=['research'],permissions={'delegate':True,'mcp_servers':['gmail']},goal='Keep customers successful')['agent']
        agent_prompt.set_manual_instructions(source,'Always give refunds to the user for approval before sending.')
        profile=agent_prompt.get_instruction_profile(source);profile['learned_rules']=['Temporary learned rule that belongs only to Ada'];data=agent_prompt._load();data['agents'][source['id']]=profile;agent_prompt._save(data)
        routine,_=routine_engine.create_routine('Create a routine called Daily Inbox that daily at 9 AM check customer inbox',owner_agent_id=source['id'])
        result=agent_lifecycle.duplicate_agent('Ada','Ava');target=result['agent'];target_profile=agent_prompt.get_instruction_profile(target)
        self.assertTrue(result['created']);self.assertEqual(target['role'],source['role']);self.assertEqual(target['goal'],source['goal']);self.assertEqual(target['skills'],source['skills'])
        self.assertEqual(target['permissions']['mcp_servers'],['gmail']);self.assertTrue(target['permissions']['delegate']);self.assertEqual(target_profile['manual_instructions'],profile['manual_instructions']);self.assertEqual(target_profile['learned_rules'],[])
        self.assertFalse(result['memory_copied']);self.assertFalse(result['conversation_copied']);self.assertEqual(len(result['routines']),1);self.assertNotEqual(result['routines'][0]['id'],routine['id']);self.assertEqual(result['routines'][0]['owner_agent_id'],target['id'])

    def test_user_created_team_requires_explicit_delegation_for_lead_and_adds_context_only(self):
        worker=agent_registry.create_agent('Ben','Customer follow-up owner')['agent'];lead=agent_registry.create_agent('Cora','Operations coordinator',permissions={'delegate':True})['agent'];plain=agent_registry.create_agent('Mira','Research owner')['agent']
        with self.assertRaises(ValueError):agent_teams.create_team('Customer Ops',[worker['id'],plain['id']],lead_agent_id=plain['id'])
        team=agent_teams.create_team('Customer Ops',[worker['id'],lead['id']],lead_agent_id=lead['id'],goal='Resolve customer issues quickly',instructions='Share bounded results, not private chat memory.')
        context=agent_teams.team_context(worker)
        self.assertEqual(team['lead_agent_id'],lead['id']);self.assertIn('Customer Ops',context);self.assertIn('Resolve customer issues quickly',context);self.assertIn('does not grant tools',context)
        self.assertFalse(worker['permissions']['delegate'])

    def test_deleted_agent_is_sanitized_out_of_team_membership(self):
        a=agent_registry.create_agent('Ada','Owner')['agent'];b=agent_registry.create_agent('Ben','Owner')['agent'];team=agent_teams.create_team('Ops',[a['id'],b['id']])
        agent_registry.delete_agent(a['id']);saved=agent_teams.get_team(team['id'])
        self.assertNotIn(a['id'],saved['member_ids']);self.assertEqual(saved['member_names'],['Ben'])

    def test_autonomous_agent_delegation_creates_visible_thread_and_real_team_job(self):
        sender=agent_registry.create_agent('Cora','Coordinator',permissions={'delegate':True})['agent'];target=agent_registry.create_agent('Ben','Follow-up owner')['agent']
        with patch.object(agent_threads,'start_team_job') as start:
            result=agent_threads.agent_to_agent_task(sender['id'],target['id'],'Review the customer issue')
        self.assertEqual(result['job']['agent_ids'],[target['id']]);start.assert_called_once_with(result['job']['id']);self.assertEqual(result['message']['sender_type'],'agent');self.assertTrue(result['message']['metadata']['materialize_replies'])
        thread=agent_threads.get_thread(result['thread']['id']);self.assertEqual(set(thread['participant_ids']),{sender['id'],target['id']})

    def test_agent_delegation_requires_permission_not_job_title(self):
        sender=agent_registry.create_agent('Boss','Chief of Staff')['agent'];target=agent_registry.create_agent('Ben','Worker')['agent']
        with self.assertRaises(ValueError):agent_threads.agent_to_agent_task(sender['id'],target['id'],'Do work')

    def test_agent_thread_messages_and_materialized_replies_publish_automation_events_once(self):
        sender=agent_registry.create_agent('Cora','Coordinator',permissions={'delegate':True})['agent'];target=agent_registry.create_agent('Ben','Worker')['agent']
        with patch.object(agent_threads,'start_team_job'):
            result=agent_threads.agent_to_agent_task(sender['id'],target['id'],'Review issue')
        jid=result['job']['id'];hid=result['job']['handoffs'][0]['id']
        team_orchestrator._finish_job(jid,[(hid,'Reviewed and resolved',None)]);agent_threads.thread_card(agent_threads.get_thread(result['thread']['id']));agent_threads.thread_card(agent_threads.get_thread(result['thread']['id']))
        events=automation_events.recent_events();message_events=[x for x in events if x['type']=='agent_thread.message'];reply_events=[x for x in events if x['type']=='agent_thread.agent_reply']
        self.assertEqual(len(message_events),1);self.assertEqual(len(reply_events),1);self.assertEqual(reply_events[0]['payload']['sender_name'],'Ben')

    def test_skill_export_and_import_use_portable_json_without_taught_browser_binding(self):
        skill=workflow_skills.create_workflow_skill(name='Invoice Review',description='Review invoices safely',when_to_use='When an invoice arrives',required_inputs=['invoice'],required_access=['files'],steps=['Read invoice','Validate totals'],decision_rules=['Flag mismatch'],expected_output='Verified review',validation_rules=['Totals reconcile'],approval_boundaries=['Payment requires approval'],failure_handling='Stop on missing invoice',source_workflow_id='wf_local_only',status='active')
        exported=skill_portability.export_skill(skill['id']);filename=exported['card']['name'];self.assertTrue((file_service.UPLOADS/filename).exists())
        workflow_skills.delete_workflow_skill(skill['id']);imported=skill_portability.import_skill_from_upload(filename)
        self.assertEqual(imported['name'],'Invoice Review');self.assertEqual(imported['steps'],['Read invoice','Validate totals']);self.assertEqual(imported['status'],'draft');self.assertIsNone(imported['source_workflow_id'])

    def test_capability_gap_reuses_existing_agent_or_recommends_without_auto_creating(self):
        existing=agent_registry.create_agent('Mira','Customer research owner')['agent']
        with patch.object(capability_planner,'rank_agents',return_value=[{'agent':existing,'score':.72}]):covered=capability_planner.analyze_capability_gap('research customer complaints')
        self.assertTrue(covered['covered']);self.assertEqual(covered['best_match']['id'],existing['id']);self.assertIsNone(covered['suggested_agent'])
        with patch.object(capability_planner,'rank_agents',return_value=[]),patch.object(capability_planner,'draft_agent_spec',return_value={'job':'New ownership','skills':[],'plugins':[]}):gap=capability_planner.analyze_capability_gap('run a completely uncovered process')
        self.assertFalse(gap['covered']);self.assertEqual(gap['recommendation'],'consider_new_agent');self.assertEqual(len(agent_registry.list_agents()),1)

    def test_platform_router_adds_chat_event_routines_and_routes_new_platform_primitives(self):
        result=platform_router.route_platform_command('Create a routine called Watch Chat that when a group chat message summarize it')
        self.assertEqual(result['card']['trigger_type'],'event');self.assertEqual(result['card']['event_type'],'agent_thread.message')
        self.assertIsNotNone(platform_router.route_platform_command('Show teams'))

    def test_runtime_source_includes_team_context_plugin_inspection_and_visible_agent_delegation(self):
        runner=Path('agentie/core/runner.py').read_text(encoding='utf-8');tools=Path('agentie/tools/persistent_tools.py').read_text(encoding='utf-8');threads=Path('agentie/core/agent_threads.py').read_text(encoding='utf-8')
        self.assertIn('team_context(persistent_agent)',runner);self.assertIn('inspect_plugin',tools);self.assertIn('delegate_to_agent',tools);self.assertIn('agent_to_agent_task',tools);self.assertIn('materialize_replies',threads)
        self.assertNotIn('agent.get("role")',tools);self.assertNotIn('agent.get("base")',tools)


if __name__=='__main__':unittest.main()
