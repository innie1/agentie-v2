import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import result_memory
from agentie.core.office_artifacts import _resolve_content
from agentie.core.team_orchestrator import team_job_card


class TypedResultsTeamUIRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=result_memory.RESULTS_FILE;result_memory.RESULTS_FILE=Path(self.temp.name)/'results.json'

    def tearDown(self):
        result_memory.RESULTS_FILE=self.old;self.temp.cleanup()

    def test_last30days_reference_beats_unrelated_latest_chat_text(self):
        card={'type':'last30days','topic':'AI agent trends','answer':'What I learned\n\nPractical signals\n• [L1] Agents are moving into production.','source_counts':{'github':2},'sources':[{'id':'L1','title':'Agent report','url':'https://example.com/a','source':'web'}]}
        result_memory.remember_global_result('',card)
        with patch('agentie.core.office_artifacts.latest_assistant_text',return_value='Started team job team_123 with Mira and Vera.'):
            content=_resolve_content('agent:alex:main','create a docx with the last 30day searche')
        self.assertIn('Last30Days Research: AI agent trends',content)
        self.assertIn('Agents are moving into production',content)
        self.assertNotIn('Started team job',content)

    def test_team_card_exposes_completion_time_for_grace_period(self):
        job={'id':'team_1','task':'Review launch','status':'completed','agent_names':['Mira','Vera'],'handoffs':[{'id':'h1','to_agent_name':'Mira','status':'completed','attempts':1},{'id':'h2','to_agent_name':'Vera','status':'completed','attempts':1}],'final_output':'Done','finished_at':'2026-08-21T01:00:00+01:00','updated_at':'2026-08-21T01:00:00+01:00'}
        card=team_job_card(job)
        self.assertEqual(card['finished_at'],job['finished_at'])
        self.assertEqual(card['type'],'team_job')

    def test_team_job_has_native_renderer_and_no_json_fallback(self):
        ui=Path('frontend/plugin_access.js').read_text(encoding='utf-8')
        self.assertIn("function renderTeamJob",ui)
        self.assertIn("card?.type==='team_job'",ui)
        self.assertIn("return renderTeamJob(card)",ui)
        self.assertIn("card?.type==='team_jobs'",ui)

    def test_collaboration_icons_wait_sixty_seconds_after_completion(self):
        ui=Path('frontend/plugin_access.js').read_text(encoding='utf-8')
        self.assertIn('(Date.now()-t)<60000',ui)
        self.assertIn('recentTerminal',ui)
        self.assertIn("['queued','working'].includes(j.status)||recentTerminal(j)",ui)
        self.assertIn('row?.click()',ui)
        self.assertIn('b.title=a.name',ui)


if __name__=='__main__':unittest.main()
