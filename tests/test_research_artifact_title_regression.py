import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agentie.core import file_service, pdf_service
from agentie.core.deep_research import Source, synthesis_prompt


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


if __name__=='__main__':unittest.main()
