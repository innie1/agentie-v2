import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agentie.core import file_service, pdf_service, job_engine
from agentie.core.deep_research import Source, synthesis_prompt
from agentie.core.npc_brain import job_title


class ResearchArtifactTitleRegressionTests(unittest.TestCase):
    def test_deep_research_prompt_requires_topic_title_before_sections(self):
        prompt=synthesis_prompt(
            'Best church management apps for small Nigerian churches',
            ['church management apps Nigeria'],
            [Source('S1','Example','https://example.com','Evidence','Evidence','church management apps Nigeria')],
        )
        self.assertIn('exactly one level-1 Markdown heading',prompt)
        self.assertIn('directly names the research topic',prompt)
        self.assertIn('Do not use a generic section heading',prompt)

    def test_pdf_without_explicit_filename_uses_document_title(self):
        content='''# Best Church Management Apps for Small Nigerian Churches Report

## Executive Summary & Context
Useful research content.
'''
        with TemporaryDirectory() as tmp, patch.object(file_service,'UPLOADS',Path(tmp)), patch.object(pdf_service,'UPLOADS',Path(tmp)):
            card=pdf_service.create_pdf(content,None,'Alex','research')
            self.assertEqual(card['document_name'],'Best Church Management Apps for Small Nigerian Churches Report')
            self.assertTrue(card['name'].startswith('Alex-Best-Church-Management-Apps'))
            self.assertTrue(card['name'].endswith('.pdf'))
            self.assertTrue(Path(tmp,card['name']).exists())

    def test_compound_job_artifact_uses_job_title_not_internal_section_heading(self):
        goal='Research the best church management apps for small Nigerian churches, compare at least 5 competitors, then create a PDF report from your completed research.'
        expected=job_title(goal)
        job={'id':'job1','session_id':'agent:agt_demo:main','goal':goal}
        step={'id':'s2','specialist':'artifact_pdf','instruction':'Create PDF file','depends_on':['s1']}
        by={'s1':{'output':'## Executive Summary & Context\n\nResearch findings here.'}}
        fake={'type':'file','name':'Alex-report.pdf','document_name':expected,'creator':'Alex'}
        with patch('agentie.core.result_memory.existing_artifact',return_value=None), \
             patch('agentie.core.result_memory.remember_artifact'), \
             patch('agentie.core.artifact_naming.creator_from_session',return_value='Alex'), \
             patch('agentie.core.pdf_service.create_pdf',return_value=fake) as create:
            job_engine._create_artifact_step(job,step,by)
        content,filename,creator,_style=create.call_args.args
        self.assertTrue(content.startswith(f'# {expected}\n\n'))
        self.assertEqual(filename,f'{expected}.pdf')
        self.assertEqual(creator,'Alex')


if __name__=='__main__':unittest.main()
