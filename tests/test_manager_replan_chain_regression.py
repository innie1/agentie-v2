import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import agent_registry,automation_events,failure_recovery,manager_autopilot,team_orchestrator


class ManagerReplanChainRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);root=Path(self.temp.name)
        self.patches=[patch.object(agent_registry,'WORKSPACE',root),patch.object(agent_registry,'AGENTS_FILE',root/'agents.json'),patch.object(team_orchestrator,'WORKSPACE',root),patch.object(team_orchestrator,'TEAM_FILE',root/'team_jobs.json'),patch.object(automation_events,'WORKSPACE',root),patch.object(automation_events,'EVENTS',root/'automation_events.json')]
        for p in self.patches:p.start()
        self.manager=agent_registry.create_agent('Cora','Operations coordinator',permissions={'delegate':True})['agent']
        self.a=agent_registry.create_agent('Ada','Customer issue investigator')['agent'];self.b=agent_registry.create_agent('Ben','Customer issue investigator')['agent'];self.c=agent_registry.create_agent('Cleo','Customer issue investigator')['agent'];self.d=agent_registry.create_agent('Dayo','Customer issue investigator')['agent']

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def _failed_job(self,error='temporary network timeout'):
        job=team_orchestrator.create_team_job('investigate customer issue',[self.a],requested_by=self.manager['id']);hid=job['handoffs'][0]['id']
        def fail(j):
            j.update(status='failed',autopilot=True,autopilot_manager_id=self.manager['id'],autopilot_recovery_enabled=True,autopilot_recovery_finalized=False,replan_count=0,recovery_history=[])
            j['handoffs'][0].update(status='failed',error=error,attempts=1)
        team_orchestrator._mutate(job['id'],fail);return team_orchestrator.get_team_job(job['id']),hid

    def _ranking(self):return [{'agent':self.manager,'score':.99},{'agent':self.b,'score':.9},{'agent':self.c,'score':.85},{'agent':self.d,'score':.8},{'agent':self.a,'score':.7}]

    def test_recovery_chain_never_reuses_already_attempted_agents(self):
        job,first=self._failed_job()
        with patch.object(failure_recovery,'rank_agents',return_value=self._ranking()):
            one=failure_recovery.replan_failed_handoff(job['id'],first);self.assertEqual(one['agent']['id'],self.b['id']);b=one['handoff']['id']
            team_orchestrator._mutate(job['id'],lambda j:next(x for x in j['handoffs'] if x['id']==b).update(status='failed',error='tool execution failed',attempts=1))
            two=failure_recovery.replan_failed_handoff(job['id'],b);self.assertEqual(two['agent']['id'],self.c['id']);c=two['handoff']['id']
            team_orchestrator._mutate(job['id'],lambda j:next(x for x in j['handoffs'] if x['id']==c).update(status='failed',error='temporary connection unavailable',attempts=1))
            three=failure_recovery.replan_failed_handoff(job['id'],c);self.assertEqual(three['agent']['id'],self.d['id'])
        latest=team_orchestrator.get_team_job(job['id']);self.assertEqual(latest['replan_count'],3);self.assertEqual([x['to_agent'] for x in latest['recovery_history']],['Ben','Cleo','Dayo'])

    def test_success_on_third_replacement_marks_entire_chain_recovered(self):
        job,first=self._failed_job()
        with patch.object(failure_recovery,'rank_agents',return_value=self._ranking()):
            one=failure_recovery.replan_failed_handoff(job['id'],first);b=one['handoff']['id'];team_orchestrator._mutate(job['id'],lambda j:next(x for x in j['handoffs'] if x['id']==b).update(status='failed',error='timeout',attempts=1))
            two=failure_recovery.replan_failed_handoff(job['id'],b);c=two['handoff']['id'];team_orchestrator._mutate(job['id'],lambda j:next(x for x in j['handoffs'] if x['id']==c).update(status='failed',error='timeout',attempts=1))
            three=failure_recovery.replan_failed_handoff(job['id'],c);d=three['handoff']['id']
        team_orchestrator._mutate(job['id'],lambda j:next(x for x in j['handoffs'] if x['id']==d).update(status='completed',result='verified recovery result',error=None))
        final=failure_recovery.finalize_recovery_chain(job['id'],d);by={x['id']:x for x in final['handoffs']}
        self.assertEqual(by[first]['status'],'recovered');self.assertEqual(by[b]['status'],'recovered');self.assertEqual(by[c]['status'],'recovered');self.assertEqual(by[d]['status'],'completed');self.assertEqual(final['status'],'completed');self.assertIn('verified recovery result',final['final_output'])

    def test_recovered_completion_emits_final_team_event_once(self):
        job=team_orchestrator.create_team_job('recovered task',[self.a],requested_by=self.manager['id'])
        def completed(j):
            j.update(status='completed',autopilot=True,autopilot_manager_id=self.manager['id'],autopilot_recovery_enabled=True,autopilot_recovery_finalized=False,replan_count=2,final_output='real recovered result')
            j['handoffs'][0].update(status='completed',result='real recovered result',error=None)
        team_orchestrator._mutate(job['id'],completed)
        manager_autopilot._finish_controller(job['id']);manager_autopilot._finish_controller(job['id'])
        events=[x for x in automation_events.recent_events() if x['type']=='team_job.completed']
        self.assertEqual(len(events),1);self.assertEqual(events[0]['payload']['team_job_id'],job['id']);self.assertEqual(events[0]['payload']['replan_count'],2)

    def test_fourth_replacement_is_blocked_by_safety_limit(self):
        job,first=self._failed_job()
        with patch.object(failure_recovery,'rank_agents',return_value=self._ranking()):
            one=failure_recovery.replan_failed_handoff(job['id'],first);b=one['handoff']['id'];team_orchestrator._mutate(job['id'],lambda j:next(x for x in j['handoffs'] if x['id']==b).update(status='failed',error='timeout',attempts=1))
            two=failure_recovery.replan_failed_handoff(job['id'],b);c=two['handoff']['id'];team_orchestrator._mutate(job['id'],lambda j:next(x for x in j['handoffs'] if x['id']==c).update(status='failed',error='timeout',attempts=1))
            three=failure_recovery.replan_failed_handoff(job['id'],c);d=three['handoff']['id'];team_orchestrator._mutate(job['id'],lambda j:next(x for x in j['handoffs'] if x['id']==d).update(status='failed',error='timeout',attempts=1))
            four=failure_recovery.replan_failed_handoff(job['id'],d)
        self.assertEqual(four['action'],'stop');self.assertFalse(four['automatic']);self.assertIn('safety limit',four['reason'])

    def test_approval_or_missing_input_still_stops_before_any_reassignment(self):
        for error in ('approval required before sending','missing input: customer account'):
            with self.subTest(error=error):
                job,hid=self._failed_job(error)
                with patch.object(failure_recovery,'rank_agents',return_value=self._ranking()) as rank:decision=failure_recovery.replan_failed_handoff(job['id'],hid)
                self.assertEqual(decision['action'],'ask_user');self.assertFalse(decision['automatic']);rank.assert_not_called()

    def test_controller_source_uses_bounded_multi_hop_recovery_and_blocks_unreachable_downstream_work(self):
        source=Path('agentie/core/manager_autopilot.py').read_text(encoding='utf-8')
        self.assertIn('MAX_REPLAN_HOPS',source);self.assertIn('finalize_recovery_chain',source);self.assertIn('Blocked by an unresolved dependency or exhausted recovery path',source)


if __name__=='__main__':unittest.main()
