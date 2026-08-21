import tempfile
import unittest
from pathlib import Path

from agentie.core import project_brain,team_orchestrator


class TeamCompletionPrivacyRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root=Path(self.temp.name)
        self.old_project_workspace=project_brain.WORKSPACE
        self.old_project_file=project_brain.PROJECTS_FILE
        self.old_team_workspace=team_orchestrator.WORKSPACE
        self.old_team_file=team_orchestrator.TEAM_FILE
        project_brain.WORKSPACE=root;project_brain.PROJECTS_FILE=root/'projects.json'
        team_orchestrator.WORKSPACE=root;team_orchestrator.TEAM_FILE=root/'team_jobs.json';team_orchestrator._RUNNING.clear()

    def tearDown(self):
        project_brain.WORKSPACE=self.old_project_workspace;project_brain.PROJECTS_FILE=self.old_project_file
        team_orchestrator.WORKSPACE=self.old_team_workspace;team_orchestrator.TEAM_FILE=self.old_team_file;team_orchestrator._RUNNING.clear()
        self.temp.cleanup()

    def test_actual_team_handoff_excludes_other_workers_legacy_result(self):
        project=project_brain.create_project('Church App','Build church software','app')
        project_brain.append_project_item(project['id'],'knowledge','Mira private competitor research',{'source_agent':'Mira','audience':'all','task':'research'})
        project_brain.append_project_item(project['id'],'knowledge','Shared onboarding requirement',{'source':'manual','audience':'all'})
        alex={'id':'agt_alex','name':'Alex','role':'CTO','base':'coding'}
        job=team_orchestrator.create_team_job('Design architecture',[alex],project_id=project['id'])
        brief=job['handoffs'][0]['context']['scoped_brief']
        self.assertNotIn('Mira private competitor research',brief)
        self.assertIn('Shared onboarding requirement',brief)
        self.assertIn('YOUR ASSIGNMENT: Design architecture',brief)

    def test_worker_result_is_summary_not_automatic_shared_knowledge(self):
        project=project_brain.create_project('Church App','Build church software','app')
        project_brain.record_worker_result(project['id'],'Mira','critic','Research rivals','# Research\nPrivate findings')
        updated=project_brain.get_project(project['id'])
        self.assertEqual(len(updated['summaries']),1)
        self.assertEqual(updated['knowledge'],[])
        self.assertEqual(updated['agent_work'],[])

    def test_team_completion_event_is_delivered_once(self):
        alex={'id':'agt_alex','name':'Alex','role':'CTO','base':'coding'}
        job=team_orchestrator.create_team_job('Design architecture',[alex])
        team_orchestrator._mutate(job['id'],lambda j:j.update(status='completed',finished_at=team_orchestrator._now(),final_output='Done'))
        first=team_orchestrator.poll_team_completion_events()
        second=team_orchestrator.poll_team_completion_events()
        self.assertEqual(len(first),1)
        self.assertEqual(first[0]['card']['type'],'team_job')
        self.assertTrue(first[0]['card']['completion_event'])
        self.assertEqual(first[0]['card']['status'],'completed')
        self.assertEqual(second,[])

    def test_team_retry_resets_completion_notification_marker(self):
        alex={'id':'agt_alex','name':'Alex','role':'CTO','base':'coding'}
        job=team_orchestrator.create_team_job('Design architecture',[alex])
        hid=job['handoffs'][0]['id']
        def fail(j):
            j['status']='failed';j['completion_notified_at']=team_orchestrator._now()
            j['handoffs'][0].update(status='failed',error='temporary')
        team_orchestrator._mutate(job['id'],fail)
        # Mirror the retry reset logic without starting a provider worker.
        def reset(j):
            j['completion_notified_at']=None
            for q in j['handoffs']:
                if q['id']==hid:q.update(status='queued',error=None,progress_summary=None,status_checked_at=None)
        team_orchestrator._mutate(job['id'],reset)
        updated=team_orchestrator.get_team_job(job['id'])
        self.assertIsNone(updated.get('completion_notified_at'))
        self.assertEqual(updated['handoffs'][0]['status'],'queued')


if __name__=='__main__':
    unittest.main()
