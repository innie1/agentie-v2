import tempfile
import unittest
from pathlib import Path

from agentie.core import memory_store
from agentie.core.office_artifacts import _DOCX_RE,_resolve_content


class SpecialistExportRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.old_workspace=memory_store.WORKSPACE
        self.old_db=memory_store.DB_PATH
        memory_store.WORKSPACE=Path(self.temp.name)
        memory_store.DB_PATH=Path(self.temp.name)/'memory.sqlite3'

    def tearDown(self):
        try:memory_store._SEMANTIC_POOL.submit(lambda:None).result(timeout=15)
        except Exception:pass
        memory_store.WORKSPACE=self.old_workspace
        memory_store.DB_PATH=self.old_db
        self.temp.cleanup()

    def test_docs_file_phrase_routes_to_docx(self):
        self.assertIsNotNone(_DOCX_RE.search('make docs file with this'))
        self.assertIsNotNone(_DOCX_RE.search('make a doc file from this'))

    def test_this_prefers_latest_specialist_handoff_result(self):
        session='agent:agt_alex:main'
        memory_store.add_message(session,'assistant','Older normal chat reply',{'routed_by':'llm'})
        full='# Technical Architecture\n\nFull specialist result for Alex.'
        memory_store.add_message(session,'assistant',full,{'routed_by':'project_handoff_result','team_job_id':'team_1','project_id':'proj_1'})
        memory_store.add_message(session,'assistant','Newer short normal reply',{'routed_by':'local'})
        self.assertEqual(_resolve_content(session,'make docs file with this'),full)

    def test_specialist_result_is_session_isolated(self):
        alex='agent:agt_alex:main';mira='agent:agt_mira:main'
        memory_store.add_message(alex,'assistant','Alex architecture',{'routed_by':'project_handoff_result'})
        memory_store.add_message(mira,'assistant','Mira research',{'routed_by':'project_handoff_result'})
        self.assertEqual(_resolve_content(alex,'make docs file with this'),'Alex architecture')
        self.assertEqual(_resolve_content(mira,'make docs file with this'),'Mira research')


if __name__=='__main__':
    unittest.main()
