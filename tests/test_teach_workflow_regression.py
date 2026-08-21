import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import workflow_browser_runtime, workflow_teaching


class TeachWorkflowRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        self.workflow_file_patch=patch.object(workflow_teaching,'WORKFLOWS_FILE',root/'workflows.json')
        self.active_file_patch=patch.object(workflow_teaching,'ACTIVE_FILE',root/'active.json')
        self.workflow_file_patch.start();self.active_file_patch.start()

    def tearDown(self):
        self.active_file_patch.stop();self.workflow_file_patch.stop();self.temp.cleanup()

    def test_teaching_records_browser_actions_and_saves_reusable_workflow(self):
        started=workflow_teaching.start_recording('Publish weekly update','agt_manager')
        self.assertEqual(started['status'],'recording')
        workflow_teaching.record_browser_event({'kind':'open','url':'https://example.com/dashboard'})
        workflow_teaching.record_browser_event({'kind':'click','target':'New post'})
        workflow_teaching.record_browser_event({'kind':'fill','field':'Title','value':'Weekly update'})
        workflow_teaching.record_browser_event({'kind':'key','key':'Enter'})
        saved=workflow_teaching.stop_recording()
        self.assertEqual(saved['status'],'saved')
        self.assertEqual([x['kind'] for x in saved['steps']],['open','click','fill','key'])
        found=workflow_teaching.get_workflow('Publish weekly update','agt_manager')
        self.assertEqual(found['id'],saved['id'])

    def test_reteaching_same_named_workflow_replaces_duplicate(self):
        workflow_teaching.start_recording('Daily check')
        workflow_teaching.record_browser_event({'kind':'click','target':'Reports'})
        first=workflow_teaching.stop_recording()
        workflow_teaching.start_recording('Daily check')
        workflow_teaching.record_browser_event({'kind':'click','target':'Dashboard'})
        second=workflow_teaching.stop_recording()
        items=workflow_teaching.list_workflows()
        self.assertEqual(len(items),1)
        self.assertNotEqual(first['id'],second['id'])
        self.assertEqual(items[0]['steps'][0]['command'],'click Dashboard')

    def test_password_values_are_never_persisted(self):
        workflow_teaching.start_recording('Login flow')
        workflow_teaching.record_browser_event({'kind':'fill','field':'Password','value':'super-secret-value','secret':True})
        saved=workflow_teaching.stop_recording()
        step=saved['steps'][0]
        self.assertNotIn('super-secret-value',step['command'])
        self.assertTrue(step['metadata']['requires_input'])
        self.assertIn('<secret>',step['command'])

    def test_teach_commands_are_narrow_and_local(self):
        self.assertEqual(workflow_browser_runtime._teach_command('Teach Agentie: publish weekly update'),('start','publish weekly update'))
        self.assertEqual(workflow_browser_runtime._teach_command('Stop teaching'),('stop',None))
        self.assertEqual(workflow_browser_runtime._teach_command('Run workflow publish weekly update'),('run','publish weekly update'))
        self.assertIsNone(workflow_browser_runtime._teach_command('Research church software'))


if __name__=='__main__':unittest.main()
