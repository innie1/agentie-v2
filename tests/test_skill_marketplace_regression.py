import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import agent_access,agent_registry,automation_events,file_service,skill_marketplace,skill_registry,workflow_skills


class SkillMarketplaceRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);root=Path(self.temp.name);skills=root/'skills'
        self.patches=[
            patch.object(agent_registry,'WORKSPACE',root),patch.object(agent_registry,'AGENTS_FILE',root/'agents.json'),
            patch.object(agent_access,'GLOBAL_ACCESS_FILE',root/'capability_access.json'),
            patch.object(skill_registry,'WORKSPACE',root),patch.object(skill_registry,'SKILLS_DIR',skills),patch.object(skill_registry,'STATE',root/'skills_state.json'),
            patch.object(workflow_skills,'WORKSPACE',root),patch.object(workflow_skills,'SKILLS_DIR',skills),
            patch.object(file_service,'WORKSPACE',root),patch.object(file_service,'UPLOADS',root/'uploads'),patch.object(file_service,'EXTRACTED',root/'extracted'),
            patch.object(automation_events,'WORKSPACE',root),patch.object(automation_events,'EVENTS',root/'automation_events.json'),
        ]
        for p in self.patches:p.start()
        self.agent=agent_registry.create_agent('Fina','Finance and invoice review owner',purpose='Review invoices and financial documents')['agent']

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def test_browsing_marketplace_never_auto_installs_or_assigns(self):
        self.assertEqual(workflow_skills.list_workflow_skills(),[])
        result=skill_marketplace.search_marketplace('',agent_id=self.agent['id'])
        self.assertEqual(result['catalog_kind'],'agentie_curated_local');self.assertTrue(result['items'])
        self.assertEqual(workflow_skills.list_workflow_skills(),[]);self.assertEqual(agent_registry.get_agent(self.agent['id'])['skills'],[])

    def test_search_finds_relevant_curated_skill_and_marks_recommendation(self):
        result=skill_marketplace.search_marketplace('invoice review',agent_id=self.agent['id']);names=[x['name'] for x in result['items']]
        self.assertIn('Invoice Review',names);invoice=next(x for x in result['items'] if x['name']=='Invoice Review');self.assertEqual(invoice['source'],'agentie_curated');self.assertTrue(invoice['recommended']);self.assertIn('finance',invoice['tags'])

    def test_install_is_draft_then_explicit_assign_grants_skill(self):
        skill=skill_marketplace.install_marketplace_item('market:invoice-review');self.assertEqual(skill['status'],'draft')
        result=skill_marketplace.assign_marketplace_item('market:invoice-review',self.agent['id']);updated=agent_registry.get_agent(self.agent['id'])
        self.assertEqual(result['agent']['id'],self.agent['id']);self.assertIn(skill['id'],updated['skills']);self.assertEqual(updated['permissions']['capability_mode'],'explicit')

    def test_existing_starter_templates_are_part_of_same_catalog(self):
        result=skill_marketplace.search_marketplace('competitor research');item=next(x for x in result['items'] if x['name']=='Competitor Research')
        self.assertTrue(item['id'].startswith('starter:'));installed=skill_marketplace.install_marketplace_item(item['id']);self.assertEqual(installed['status'],'draft')

    def test_share_uses_existing_portable_skill_export(self):
        skill=skill_marketplace.install_marketplace_item('market:meeting-prep');shared=skill_marketplace.share_installed_skill(skill['id'])
        self.assertEqual(shared['skill']['id'],skill['id']);self.assertEqual(shared['card']['type'],'uploaded_file');self.assertTrue(shared['card']['name'].endswith('.json'))
        exported=(file_service.UPLOADS/shared['card']['name']).read_text(encoding='utf-8');self.assertIn('agentie.workflow-skill',exported)

    def test_marketplace_ui_exposes_search_recommend_install_assign_and_share(self):
        text=Path('frontend/platform_next4.js').read_text(encoding='utf-8')
        for marker in ('Skill Marketplace','/platform/skills/marketplace','Install draft','Install + assign','Share / export','Agentie-curated/local'):
            self.assertIn(marker,text)


if __name__=='__main__':unittest.main()
