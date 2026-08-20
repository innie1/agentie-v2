import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agentie.core import office_artifacts, pdf_service
from agentie.core.document_design import choose_style, parse_blocks, first_numeric_series


SAMPLE='''# Launch Readiness Report

## Executive summary
Agentie is approaching launch readiness with a few remaining reliability items.

## Key findings
- Core agent routing is working.
- Skills and MCP permissions are enforced.
- Computer reliability remains deferred.

## Metrics
| Area | Score |
| --- | ---: |
| Agents | 92 |
| Skills | 88 |
| Routines | 74 |
'''


class DocumentDesignRegressionTests(unittest.TestCase):
    def test_style_selection_is_not_single_template(self):
        self.assertEqual(choose_style('board strategy report').id,'executive')
        self.assertEqual(choose_style('research findings with citations').id,'research')
        self.assertEqual(choose_style('modern product launch').id,'modern')

    def test_parser_preserves_structure_and_numeric_table(self):
        blocks=parse_blocks(SAMPLE)
        self.assertTrue(any(x['type']=='heading' for x in blocks))
        self.assertTrue(any(x['type']=='bullets' for x in blocks))
        self.assertTrue(any(x['type']=='table' for x in blocks))
        self.assertIsNotNone(first_numeric_series(SAMPLE))

    def test_docx_uses_professional_layout_and_chart_pipeline(self):
        with TemporaryDirectory() as tmp, patch.object(office_artifacts,'UPLOADS',Path(tmp)):
            card=office_artifacts.create_docx(SAMPLE,'launch.docx','Alex','executive')
            self.assertEqual(card['document_style'],'executive')
            self.assertEqual(card['creator'],'Alex')
            self.assertTrue(Path(tmp,card['name']).exists())

    def test_xlsx_adds_style_and_chart_when_numeric_data_exists(self):
        with TemporaryDirectory() as tmp, patch.object(office_artifacts,'UPLOADS',Path(tmp)):
            card=office_artifacts.create_xlsx(SAMPLE,'metrics.xlsx','Mira','modern')
            self.assertEqual(card['creator'],'Mira')
            self.assertTrue(Path(tmp,card['name']).exists())

    def test_pdf_uses_style_pack_and_professional_metadata(self):
        with TemporaryDirectory() as tmp, patch.object(pdf_service,'UPLOADS',Path(tmp)):
            card=pdf_service.create_pdf(SAMPLE,'launch.pdf','Vera','research')
            self.assertEqual(card['document_style'],'research')
            self.assertEqual(card['creator'],'Vera')
            self.assertTrue(Path(tmp,card['name']).exists())


if __name__=='__main__':unittest.main()
