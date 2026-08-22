import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agentie.core import (
    activity_feed,
    agent_access,
    agent_builder,
    agent_registry,
    agent_threads,
    automation_events,
    mcp_client,
    routine_engine,
    routine_worker,
    skill_registry,
    team_orchestrator,
    workflow_browser_runtime,
    workflow_skill_runtime,
    workflow_skills,
)
from agentie.tools import approval_tools


class GrokPlatformExpansionRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);self.root=Path(self.temp.name);skills=self.root/'skills'
        self.patches=[
            patch.object(agent_registry,'WORKSPACE',self.root),patch.object(agent_registry,'AGENTS_FILE',self.root/'agents.json'),
            patch.object(agent_access,'GLOBAL_ACCESS_FILE',self.root/'capability_access.json'),
            patch.object(skill_registry,'WORKSPACE',self.root),patch.object(skill_registry,'SKILLS_DIR',skills),patch.object(skill_registry,'STATE',self.root/'skills_state.json'),
            patch.object(workflow_skills,'WORKSPACE',self.root),patch.object(workflow_skills,'SKILLS_DIR',skills),
            patch.object(workflow_skill_runtime,'WORKSPACE',self.root),patch.object(workflow_skill_runtime,'RUNS',self.root/'skill_runs.json'),
            patch.object(agent_threads,'WORKSPACE',self.root),patch.object(agent_threads,'THREADS',self.root/'agent_threads.json'),
            patch.object(team_orchestrator,'WORKSPACE',self.root),patch.object(team_orchestrator,'TEAM_FILE',self.root/'team_jobs.json'),
            patch.object(routine_engine,'WORKSPACE',self.root),patch.object(routine_engine,'ROUTINES',self.root/'routines.json'),patch.object(routine_engine,'RUNS',self.root/'routine_runs.json'),
            patch.object(routine_worker,'WORKSPACE',self.root),patch.object(routine_worker,'EVENTS',self.root/'routine_events.json'),
            patch.object(automation_events,'WORKSPACE',self.root),patch.object(automation_events,'EVENTS',self.root/'automation_events.json'),
            patch.object(mcp_client,'REGISTRY',self.root/'mcp_servers.json'),patch.object(approval_tools,'STORE',self.root/'approvals.json'),
        ]
        for item in self.patches:item.start()

    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.temp.cleanup()

    def _skill(self,name='Weekly Summary',**extra):
        return workflow_skills.create_workflow_skill(name=name,when_to_use='When this repeatable work is requested',steps=['Do the real work','Validate the result'],expected_output='A verified result',approval_boundaries=["Use Agentie's normal approval path for consequential actions."],status='active',**extra)

    def _agent_with_skill(self,skill,name='Ada'):
        return agent_registry.create_agent(name,'Configured work owner',skills=[skill['id']])['agent']

    def test_manual_skill_executes_through_assigned_persistent_agent_and_records_run(self):
        skill=self._skill();agent=self._agent_with_skill(skill)
        with patch('agentie.core.runner.run_agent',new=AsyncMock(return_value='Verified result')) as run:
            result=asyncio.run(workflow_skill_runtime.execute_workflow_skill(skill['id'],agent['session_prefix']+'main'))
        self.assertEqual(result['status'],'completed');self.assertEqual(result['run']['result'],'Verified result')
        self.assertIn(agent['session_prefix']+'skill:',run.await_args.args[2]);self.assertEqual(workflow_skill_runtime.list_skill_runs(agent_id=agent['id'])[0]['skill_id'],skill['id'])

    def test_manual_skill_missing_input_or_assignment_never_fakes_execution(self):
        skill=self._skill('Invoice Review',required_inputs=['invoice']);assigned=self._agent_with_skill(skill);unassigned=agent_registry.create_agent('Ben','Invoice owner')['agent']
        with patch('agentie.core.runner.run_agent',new=AsyncMock(return_value='should not run')) as run:
            missing=asyncio.run(workflow_skill_runtime.execute_workflow_skill(skill['id'],assigned['session_prefix']+'main'))
            denied=asyncio.run(workflow_skill_runtime.execute_workflow_skill(skill['id'],unassigned['session_prefix']+'main',inputs={'invoice':'invoice.pdf'}))
        self.assertEqual(missing['status'],'needs_input');self.assertIn('invoice',missing['missing_inputs']);self.assertEqual(denied['status'],'needs_access');run.assert_not_awaited()

    def test_skill_run_never_persists_protected_input_values(self):
        safe=workflow_skill_runtime._safe_inputs({'password':'super-secret','invoice':'invoice.pdf','api key':'sk-secret'})
        self.assertNotIn('super-secret',str(safe));self.assertNotIn('sk-secret',str(safe));self.assertEqual(safe['invoice'],'invoice.pdf');self.assertIn('not stored',safe['password'])

    def test_taught_skill_keeps_deterministic_browser_replay(self):
        skill=self._skill('Publish Update',source_workflow_id='wf_123');agent=self._agent_with_skill(skill)
        fake={'id':'wf_123','name':'Publish Update','steps':[]};sentinel={'message':'deterministic','card':{'type':'browser_actions'}}
        with patch.object(workflow_browser_runtime,'get_workflow',return_value=fake),patch.object(workflow_browser_runtime,'_replay',new=AsyncMock(return_value=sentinel)) as replay,patch('agentie.core.workflow_skill_runtime.execute_workflow_skill',new=AsyncMock()) as generic:
            result=asyncio.run(workflow_browser_runtime._run_skill(skill['name'],agent['session_prefix']+'main'))
        self.assertIs(result,sentinel);replay.assert_awaited_once();generic.assert_not_awaited()

    def test_builder_recommends_real_team_schedule_and_connections_without_hidden_authority(self):
        coordinator=agent_registry.create_agent('Cora','Operations coordinator',permissions={'delegate':True})['agent'];agent_registry.create_agent('Mira','Customer research owner',purpose='Research customer complaints and needs')
        fake_plugins=[{'id':'gmail','name':'Gmail','description':'Email and customer inbox','capabilities':['email']}]
        with patch.object(agent_builder,'mcp_presets',return_value=fake_plugins),patch.object(agent_builder,'list_servers',return_value=[]):
            ordinary=agent_builder.draft_agent_spec('Handle customer email and research complaints.',name='Ada',job='Support owner')
            explicit=agent_builder.draft_agent_spec('Handle customer email, reports to Cora, and every Monday at 9 AM summarize complaints.',name='Ada',job='Support owner')
            coordinator_draft=agent_builder.draft_agent_spec('Coordinate the team and delegate work.',name='Lead',job='Work coordinator')
        self.assertIsNone(ordinary['recommended_manager']);self.assertEqual(explicit['recommended_manager']['id'],coordinator['id'])
        self.assertTrue(explicit['routine_suggestions']);self.assertFalse(ordinary['routine_suggestions']);self.assertTrue(coordinator_draft['can_delegate_recommended'])
        self.assertIn('gmail',explicit['connection_needed']);self.assertTrue(any(x['kind']=='plugin' and x['id']=='gmail' for x in explicit['capability_gaps']))
        self.assertTrue(all(x['id'] in {a['id'] for a in agent_registry.list_agents()} for x in explicit['recommended_collaborators']))

    def test_multi_agent_mentions_create_one_real_parallel_team_job(self):
        ada=agent_registry.create_agent('Ada','Support owner')['agent'];ben=agent_registry.create_agent('Ben','Follow-up owner')['agent'];thread=agent_threads.create_thread('Customer Ops',[ada['id'],ben['id']])
        with patch.object(agent_threads,'start_team_job') as start:row=agent_threads.post_message(thread['id'],'user',None,'User','@Ada @Ben compare today’s customer issues')
        jobs=team_orchestrator.list_team_jobs();self.assertEqual(len(jobs),1);self.assertEqual(set(jobs[0]['agent_ids']),{ada['id'],ben['id']});start.assert_called_once_with(jobs[0]['id'])
        self.assertEqual(set(row['metadata']['mentions']),{'Ada','Ben'});self.assertNotIn('@Ada',jobs[0]['task']);self.assertNotIn('@Ben',jobs[0]['task'])

    def test_completed_handoffs_materialize_as_agent_replies_exactly_once(self):
        ada=agent_registry.create_agent('Ada','Support owner')['agent'];ben=agent_registry.create_agent('Ben','Follow-up owner')['agent'];thread=agent_threads.create_thread('Customer Ops',[ada['id'],ben['id']])
        with patch.object(agent_threads,'start_team_job'):origin=agent_threads.post_message(thread['id'],'user',None,'User','@Ada @Ben review this')
        jid=origin['metadata']['team_job_id']
        def finish(job):
            job['status']='completed';job['finished_at']='2026-08-22T20:00:00+00:00';job['final_output']='done'
            for h in job['handoffs']:h.update(status='completed',result=f"{h['to_agent_name']} result",error=None,finished_at=job['finished_at'])
        team_orchestrator._mutate(jid,finish);first=agent_threads.thread_card(agent_threads.get_thread(thread['id']));second=agent_threads.thread_card(agent_threads.get_thread(thread['id']))
        replies=[x for x in first['messages'] if x.get('sender_type')=='agent'];again=[x for x in second['messages'] if x.get('sender_type')=='agent']
        self.assertEqual(len(replies),2);self.assertEqual(len(again),2);self.assertEqual({x['sender_name'] for x in replies},{'Ada','Ben'});self.assertTrue(all((x.get('metadata') or {}).get('reply_to_message_id')==origin['id'] for x in replies))

    def test_natural_event_routine_creation_uses_existing_routine_engine(self):
        agent=agent_registry.create_agent('Ada','Support owner')['agent'];result=routine_engine.route_routine_command('Create a routine called Follow Up that when a skill run completes summarize the result',owner_agent_id=agent['id']);item=result['card']
        self.assertEqual(item['trigger_type'],'event');self.assertEqual(item['event_type'],'skill_run.completed');self.assertEqual(item['owner_agent_id'],agent['id']);self.assertEqual(item['action'],'summarize the result')

    def test_event_routine_dispatches_once_and_closes_durable_event(self):
        agent=agent_registry.create_agent('Ada','Support owner')['agent'];routine,_=routine_engine.create_event_routine(name='Follow Up',event_type='team_job.completed',action='summarize result',owner_agent_id=agent['id']);event=automation_events.publish_event('team_job.completed',{'team_job_id':'team_1'},source='test')
        with patch.object(routine_worker,'_execute_routine',new=AsyncMock()) as execute:
            asyncio.run(routine_worker._dispatch_internal_events());asyncio.run(routine_worker._dispatch_internal_events())
        execute.assert_awaited_once();latest=next(x for x in automation_events.recent_events() if x['id']==event['id']);self.assertIsNotNone(latest['closed_at']);self.assertIn(routine['id'],latest['delivered_routine_ids']);self.assertEqual(routine_engine.list_routines(agent['id'])[0]['run_count'],1)

    def test_linked_manual_skill_routine_executes_under_owner_and_tags_source(self):
        skill=self._skill();agent=self._agent_with_skill(skill);routine,_=routine_engine.create_routine('Create a routine called Daily Skill that daily at 9 AM run the saved skill',owner_agent_id=agent['id'],skill_id=skill['id']);completed={'status':'completed','message':'done','card':{'type':'note'},'run':{'id':'skillrun_test'}}
        with patch('agentie.core.workflow_skill_runtime.execute_workflow_skill',new=AsyncMock(return_value=completed)) as run:asyncio.run(routine_worker._run_linked_skill(routine))
        run.assert_awaited_once();self.assertEqual(run.await_args.args[0],skill['id']);self.assertTrue(run.await_args.args[1].startswith(agent['session_prefix']+'routine:'));self.assertEqual(run.await_args.kwargs['source'],f"routine:{routine['id']}")
        recorded=routine_engine.list_runs(routine_id=routine['id'])[0];self.assertEqual(recorded['status'],'completed');self.assertEqual(recorded['skill_run_id'],'skillrun_test')

    def test_taught_skill_routine_preserves_approval_input_and_failure_status(self):
        self.assertEqual(routine_worker._browser_skill_status({'card':{'type':'browser_approval'},'message':'approval'}),'awaiting_approval')
        self.assertEqual(routine_worker._browser_skill_status({'card':{'type':'note'},'message':'This workflow contains a protected value'}),'needs_input')
        self.assertEqual(routine_worker._browser_skill_status({'card':{'type':'browser_actions','title':'Workflow failed · Test'},'message':'failed'}),'failed')

    def test_skill_event_routine_cannot_retrigger_itself_forever(self):
        skill=self._skill();agent=self._agent_with_skill(skill);routine,_=routine_engine.create_event_routine(name='React to Skill',event_type='skill_run.completed',action='run it again',owner_agent_id=agent['id'],skill_id=skill['id']);event=automation_events.publish_event('skill_run.completed',{'skill_id':skill['id'],'source':f"routine:{routine['id']}"},source='workflow_skill_runtime')
        with patch.object(routine_worker,'_execute_routine',new=AsyncMock()) as execute:asyncio.run(routine_worker._dispatch_internal_events())
        execute.assert_not_awaited();latest=next(x for x in automation_events.recent_events() if x['id']==event['id']);self.assertIsNotNone(latest['closed_at']);self.assertEqual(routine_engine.list_routines(agent['id'])[0]['run_count'],0)

    def test_approval_resolution_and_team_completion_publish_internal_events(self):
        approval=approval_tools.create_approval('test:danger','Need a decision',{'agent_id':'agt_test','agent_name':'Ada','kind':'test'});approval_tools.resolve_approval(approval['id'],False);self.assertTrue(any(x['type']=='approval.resolved' for x in automation_events.recent_events()))
        agent=agent_registry.create_agent('Ben','Worker')['agent'];job=team_orchestrator.create_team_job('Do the bounded work',[agent]);hid=job['handoffs'][0]['id'];team_orchestrator._finish_job(job['id'],[(hid,'real result',None)])
        events=automation_events.recent_events();self.assertTrue(any(x['type']=='team_job.completed' and x['payload'].get('team_job_id')==job['id'] for x in events))

    def test_activity_feed_merges_authoritative_existing_stores(self):
        skill=self._skill();agent=self._agent_with_skill(skill);run=workflow_skill_runtime._new_run(skill,agent,None,'user','test');workflow_skill_runtime._mutate(run['id'],status='completed',result='skill result',finished_at='2026-08-22T20:01:00+00:00')
        routine,_=routine_engine.create_routine('Create a routine called Daily Summary that daily at 9 AM summarize activity',owner_agent_id=agent['id']);routine_engine.record_run(routine['id'],None,'completed');team_orchestrator.create_team_job('Review customer issues',[agent]);approval_tools.create_approval('mcp:test:send:{}','Allow send',{'kind':'mcp','agent_id':agent['id'],'agent_name':agent['name'],'server':'test','tool':'send'})
        fake_trace={'id':'trace1','session_id':agent['session_prefix']+'main','user_message':'Do work','status':'completed','routed_by':'llm','started_at':'2026-08-22T20:00:00+00:00','finished_at':'2026-08-22T20:00:01+00:00','provider_calls':1,'total_tokens':10}
        with patch.object(activity_feed,'recent_traces',return_value=[fake_trace]):items=activity_feed.activity_items(agent_id=agent['id'],limit=50)
        kinds={x['kind'] for x in items};self.assertTrue({'trace','collaboration','skill','routine','approval'}.issubset(kinds));self.assertEqual(len({x['id'] for x in items}),len(items))

    def test_activity_command_and_platform_ui_expose_new_primitives_cleanly(self):
        sentinel={'type':'note','title':'Activity timeline','content':'ok'}
        with patch('agentie.core.activity_feed.activity_note',return_value=sentinel):result=skill_registry.route_skill_command('Show activity timeline')
        self.assertIs(result['card'],sentinel);ui=Path('frontend/platform.js').read_text(encoding='utf-8');browser=Path('agentie/core/workflow_browser_runtime.py').read_text(encoding='utf-8')
        self.assertIn('@mention multiple agents',ui);self.assertIn('Reusable Skills',ui);self.assertIn('Activity',ui);self.assertIn('recommended_collaborators',ui);self.assertIn('routine_suggestions',ui);self.assertIn('can_delegate_recommended',ui)
        self.assertIn('execute_workflow_skill',browser);self.assertIn('.base-agent-label,#agentType{display:none!important}',ui)


if __name__=='__main__':unittest.main()
