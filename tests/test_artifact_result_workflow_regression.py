import tempfile
import unittest
from pathlib import Path

from agentie.core import file_service,job_engine,memory_store,office_artifacts,result_memory
from agentie.core.office_artifacts import try_office_request


class ArtifactResultWorkflowRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root=Path(self.temp.name)
        self.old={
            'memory_workspace':memory_store.WORKSPACE,'memory_db':memory_store.DB_PATH,
            'result_workspace':result_memory.WORKSPACE,'result_file':result_memory.RESULTS_FILE,
            'file_workspace':file_service.WORKSPACE,'uploads':file_service.UPLOADS,'extracted':file_service.EXTRACTED,
            'office_uploads':office_artifacts.UPLOADS,
            'job_workspace':job_engine.WORKSPACE,'job_db':job_engine.DB_PATH,
        }
        memory_store.WORKSPACE=root;memory_store.DB_PATH=root/'memory.sqlite3'
        result_memory.WORKSPACE=root;result_memory.RESULTS_FILE=root/'result_memory.json'
        file_service.WORKSPACE=root;file_service.UPLOADS=root/'uploads';file_service.EXTRACTED=root/'extracted';office_artifacts.UPLOADS=file_service.UPLOADS
        job_engine.WORKSPACE=root;job_engine.DB_PATH=root/'jobs.sqlite3';job_engine._RUNNING.clear()

    def tearDown(self):
        try:memory_store._SEMANTIC_POOL.submit(lambda:None).result(timeout=15)
        except Exception:pass
        memory_store.WORKSPACE=self.old['memory_workspace'];memory_store.DB_PATH=self.old['memory_db']
        result_memory.WORKSPACE=self.old['result_workspace'];result_memory.RESULTS_FILE=self.old['result_file']
        file_service.WORKSPACE=self.old['file_workspace'];file_service.UPLOADS=self.old['uploads'];file_service.EXTRACTED=self.old['extracted'];office_artifacts.UPLOADS=self.old['office_uploads']
        job_engine.WORKSPACE=self.old['job_workspace'];job_engine.DB_PATH=self.old['job_db'];job_engine._RUNNING.clear()
        self.temp.cleanup()

    def _result(self,session,title,body):
        content=f'# {title}\n\n{body} '+('detail '*40)
        memory_store.add_message(session,'assistant',content,{'routed_by':'project_handoff_result'})
        return content

    def test_multiple_results_return_native_picker(self):
        session='agent:agt_alex:main'
        self._result(session,'Architecture report','Architecture content.')
        self._result(session,'Security review','Security content.')
        response=try_office_request(session,'make docs file with this')
        self.assertEqual(response['card']['type'],'artifact_source_picker')
        self.assertEqual(response['card']['format'],'docx')
        self.assertEqual(len(response['card']['items']),2)
        self.assertTrue(all(x.get('id') and x.get('title') for x in response['card']['items']))

    def test_single_result_creates_directly_and_second_request_reuses_file(self):
        session='agent:agt_alex:main';self._result(session,'Architecture report','Architecture content.')
        first=try_office_request(session,'make docs file with this')
        self.assertEqual(first['card']['suffix'],'.docx')
        self.assertFalse(first.get('already_created',False))
        second=try_office_request(session,'make docs file with this')
        self.assertTrue(second.get('already_created'))
        self.assertEqual(second['card']['name'],first['card']['name'])
        self.assertIn('Already created',second['message'])

    def test_selected_result_id_resolves_exact_source(self):
        session='agent:agt_alex:main'
        a=self._result(session,'Architecture report','Architecture content.')
        self._result(session,'Security review','Security content.')
        candidate=next(x for x in result_memory.list_result_candidates(session) if x['content']==a)
        self.assertEqual(result_memory.resolve_result_reference(session,f'create docx from result {candidate["id"]}'),a)

    def test_research_then_pdf_is_two_step_dependency_plan(self):
        plan=job_engine.make_plan('Research Nigerian church management apps, then create a PDF with the research')
        self.assertEqual(len(plan),2)
        self.assertEqual(plan[0]['specialist'],'deep_research')
        self.assertEqual(plan[1]['specialist'],'artifact_pdf')
        self.assertEqual(plan[1]['depends_on'],['s1'])

    def test_completion_event_is_delivered_only_once(self):
        job=job_engine.create_job('agent:agt_alex:main','Write a short report')
        job_engine._set_step(job['id'],'s1',status='completed',output='Done',finished_at=job_engine._now())
        job_engine._set_job(job['id'],status='completed',final_output='Done',error=None)
        job_engine._event(job['id'],'job_completed','Job completed successfully.')
        first=job_engine.poll_job_completion_events()
        second=job_engine.poll_job_completion_events()
        self.assertEqual(len(first),1)
        self.assertEqual(first[0]['card']['type'],'job_progress')
        self.assertEqual(first[0]['card']['status'],'completed')
        self.assertEqual(second,[])

    def test_picker_ui_uses_single_select_checkboxes(self):
        raw=Path('frontend/project_workspace.js').read_text(encoding='utf-8')
        self.assertIn("card?.type==='artifact_source_picker'",raw)
        self.assertIn("check.type='checkbox'",raw)
        self.assertIn('checks.forEach(other=>{if(other!==check)other.checked=false})',raw)
        self.assertIn('Create ${String(kind||\'docx\').toUpperCase()} from result ${id}',raw)


if __name__=='__main__':
    unittest.main()
