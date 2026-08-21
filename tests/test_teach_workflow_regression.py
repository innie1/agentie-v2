import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agentie.core import browser_monitor, workflow_browser_runtime, workflow_teaching


class TeachWorkflowRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        self.workflow_file_patch=patch.object(workflow_teaching,'WORKFLOWS_FILE',root/'workflows.json')
        self.active_file_patch=patch.object(workflow_teaching,'ACTIVE_FILE',root/'active.json')
        self.workflow_file_patch.start();self.active_file_patch.start();workflow_browser_runtime._reset_probe_state()

    def tearDown(self):
        workflow_browser_runtime._reset_probe_state();self.active_file_patch.stop();self.workflow_file_patch.stop();self.temp.cleanup()

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

    def test_browser_router_checks_teach_mode_before_generic_browser_work(self):
        expected={'message':'teaching locally','card':{'type':'note'}}
        with patch.object(workflow_browser_runtime,'route_taught_workflow_request',new=AsyncMock(return_value=expected)) as taught:
            result=asyncio.run(browser_monitor.route_browser_request('Teach Agentie: publish weekly update'))
        self.assertEqual(result,expected)
        taught.assert_awaited_once()

    def test_browser_probe_adds_init_script_only_once_per_page(self):
        class FakePage:
            def __init__(self):self.added=0;self.installed=False
            async def add_init_script(self,script):self.added+=1
            async def evaluate(self,script):
                if 'Boolean(window.__agentieTeachInstalled)' in script:return self.installed
                self.installed=True;return None
        page=FakePage()
        asyncio.run(workflow_browser_runtime._install_probe(page));asyncio.run(workflow_browser_runtime._install_probe(page))
        self.assertEqual(page.added,1)

    def test_form_field_labels_never_use_the_typed_value_as_the_field_name(self):
        script=workflow_browser_runtime._TEACH_SCRIPT
        field_section=script.split('const fieldLabel = el => {',1)[1].split('const actionLabel = raw => {',1)[0]
        self.assertNotIn('el.value',field_section)
        self.assertIn("el.getAttribute?.('aria-label')",field_section)
        self.assertIn("el.getAttribute?.('placeholder')",field_section)
        self.assertIn("label[for=",field_section)

    def test_taught_workflow_ui_reuses_existing_note_and_browser_action_cards(self):
        item={'id':'wf_1','name':'Weekly update','steps':[{'command':'click Reports'}],'run_count':0}
        self.assertEqual(workflow_browser_runtime._workflow_note(item)['type'],'note')
        self.assertEqual(workflow_browser_runtime._workflow_list_note([item])['type'],'note')


if __name__=='__main__':unittest.main()
