import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from agentie.core import agent_registry, automation_events, team_orchestrator
from agentie.core.proactive import StaleHandoffConfig, scan_and_nudge


class StaleHandoffMonitorRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        self.patches = [
            patch.object(agent_registry, 'WORKSPACE', self.root), patch.object(agent_registry, 'AGENTS_FILE', self.root / 'agents.json'),
            patch.object(team_orchestrator, 'WORKSPACE', self.root), patch.object(team_orchestrator, 'TEAM_FILE', self.root / 'team_jobs.json'),
            patch.object(automation_events, 'WORKSPACE', self.root), patch.object(automation_events, 'EVENTS', self.root / 'automation_events.json'),
        ]
        for item in self.patches:item.start()
        self.now = datetime.now().astimezone()

    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.temp.cleanup()

    def _stalled_job(self, *, requested_by='user', minutes_stale=61, manager=None):
        worker = agent_registry.create_agent('Worker', 'Task owner')['agent']
        with patch.object(team_orchestrator, 'start_team_job'):
            job = team_orchestrator.create_team_job('Draft the weekly report', [worker], requested_by=requested_by)
        stale_at = (self.now - timedelta(minutes=minutes_stale)).isoformat(timespec='seconds')

        def backdate(j):
            for h in j['handoffs']:
                h['status'] = 'working'
                h['started_at'] = stale_at
                h['status_checked_at'] = stale_at
        team_orchestrator._mutate(job['id'], backdate)
        return team_orchestrator.get_team_job(job['id']), worker

    def test_untouched_recent_handoff_is_not_nudged(self):
        worker = agent_registry.create_agent('Worker', 'Task owner')['agent']
        with patch.object(team_orchestrator, 'start_team_job'):
            job = team_orchestrator.create_team_job('Draft the weekly report', [worker])
        team_orchestrator._mutate(job['id'], lambda j: [h.update(status='working') for h in j['handoffs']])
        actions = scan_and_nudge(now=self.now, config=StaleHandoffConfig(nudge_after_seconds=1800, escalate_after_nudges=2))
        self.assertEqual(actions, [])

    def test_completed_job_is_never_scanned(self):
        job, _ = self._stalled_job(minutes_stale=120)
        team_orchestrator._mutate(job['id'], lambda j: j.update(status='completed'))
        actions = scan_and_nudge(now=self.now, config=StaleHandoffConfig(nudge_after_seconds=60, escalate_after_nudges=2))
        self.assertEqual(actions, [])

    def test_stalled_handoff_gets_a_local_nudge_with_no_model_call(self):
        job, worker = self._stalled_job(minutes_stale=61)
        actions = scan_and_nudge(now=self.now, config=StaleHandoffConfig(nudge_after_seconds=60, escalate_after_nudges=2))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]['action'], 'nudged')
        updated = team_orchestrator.get_team_job(job['id'])
        handoff = updated['handoffs'][0]
        self.assertEqual(handoff['stall_nudge_count'], 1)
        self.assertIn('Checking in', handoff['progress_summary'])
        events = automation_events.recent_events(20)
        self.assertTrue(any(e['type'] == 'team_job.handoff_stalled' for e in events))

    def test_repeated_stalls_escalate_to_owning_delegate_capable_manager(self):
        manager = agent_registry.create_agent('Chief', 'Chief of staff', permissions={'delegate': True})['agent']
        job, worker = self._stalled_job(requested_by=manager['id'], minutes_stale=200)
        cfg = StaleHandoffConfig(nudge_after_seconds=60, escalate_after_nudges=2)
        with patch.object(team_orchestrator, 'start_team_job') as start:
            scan_and_nudge(now=self.now, config=cfg)  # nudge 1
            scan_and_nudge(now=self.now + timedelta(minutes=5), config=cfg)  # nudge 2
            actions = scan_and_nudge(now=self.now + timedelta(minutes=10), config=cfg)  # escalate
        self.assertEqual(actions[0]['action'], 'escalated')
        self.assertTrue(start.called)
        updated = team_orchestrator.get_team_job(job['id'])
        handoff = updated['handoffs'][0]
        self.assertTrue(handoff['stall_escalated'])
        self.assertIsNotNone(handoff['stall_escalation_job_id'])
        escalation = team_orchestrator.get_team_job(handoff['stall_escalation_job_id'])
        self.assertEqual(escalation['agent_ids'], [manager['id']])

    def test_escalation_never_repeats_once_flagged(self):
        manager = agent_registry.create_agent('Chief', 'Chief of staff', permissions={'delegate': True})['agent']
        job, worker = self._stalled_job(requested_by=manager['id'], minutes_stale=500)
        cfg = StaleHandoffConfig(nudge_after_seconds=1, escalate_after_nudges=0)
        with patch.object(team_orchestrator, 'start_team_job'):
            first = scan_and_nudge(now=self.now, config=cfg)
            second = scan_and_nudge(now=self.now + timedelta(hours=5), config=cfg)
        self.assertEqual(first[0]['action'], 'escalated')
        original_handoff_id = job['handoffs'][0]['id']
        repeat_actions_on_original = [a for a in second if a.get('handoff_id') == original_handoff_id]
        self.assertEqual(repeat_actions_on_original, [])  # already escalated; monitor leaves the original handoff alone

    def test_user_initiated_stall_never_triggers_an_automatic_model_call(self):
        job, worker = self._stalled_job(requested_by='user', minutes_stale=500)
        cfg = StaleHandoffConfig(nudge_after_seconds=1, escalate_after_nudges=0)
        with patch.object(team_orchestrator, 'start_team_job') as start:
            actions = scan_and_nudge(now=self.now, config=cfg)
        self.assertEqual(actions[0]['action'], 'needs_attention')
        start.assert_not_called()
        events = automation_events.recent_events(20)
        self.assertTrue(any(e['type'] == 'team_job.handoff_needs_attention' for e in events))


if __name__ == '__main__':
    unittest.main()
