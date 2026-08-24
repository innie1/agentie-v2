import tempfile, unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import project_brain


class ProjectBrainFullShareRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name) / 'projects.json'
        self.patch = patch.object(project_brain, 'PROJECTS_FILE', self.file)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_new_project_defaults_to_scoped(self):
        p = project_brain.create_project('App', 'Build an app', 'app')
        self.assertEqual(p['share_mode'], 'scoped')

    def test_set_share_mode_rejects_invalid_value(self):
        p = project_brain.create_project('App', 'Build an app', 'app')
        with self.assertRaises(ValueError):
            project_brain.set_share_mode(p['id'], 'everyone')

    def test_scoped_mode_still_hides_role_restricted_knowledge_and_peer_summaries(self):
        p = project_brain.create_project('App', 'Build an app', 'app')
        project_brain.append_project_item(p['id'], 'knowledge', 'Legal-only detail', {'audience': 'lawyer'})
        coder = {'id': 'a1', 'name': 'Codey', 'role': 'coder'}
        marketer = {'id': 'a2', 'name': 'Mira', 'role': 'marketer'}
        project_brain.set_agent_work(p['id'], coder, 'Build the signup flow')
        project_brain.set_agent_work(p['id'], marketer, 'Write launch copy')
        project_brain.update_agent_work_status(p['id'], 'Codey', 'completed', 'Signup flow is done, using OTP auth.')
        ctx = project_brain.project_context(project_brain.get_project(p['id']), 'marketer', 'Write launch copy', agent_name='Mira')
        self.assertNotIn('Legal-only detail', ctx)
        self.assertNotIn('Signup flow is done', ctx)
        self.assertIn("Do not import another specialist's private conversation", ctx)

    def test_full_share_command_flips_mode_and_exposes_everything(self):
        p = project_brain.create_project('App', 'Build an app', 'app')
        result = project_brain.route_project_command(f"make project {p['name']} fully shared")
        self.assertEqual(result['card']['share_mode'], 'full')
        project_brain.append_project_item(p['id'], 'knowledge', 'Legal-only detail', {'audience': 'lawyer'})
        coder = {'id': 'a1', 'name': 'Codey', 'role': 'coder'}
        marketer = {'id': 'a2', 'name': 'Mira', 'role': 'marketer'}
        project_brain.set_agent_work(p['id'], coder, 'Build the signup flow')
        project_brain.set_agent_work(p['id'], marketer, 'Write launch copy')
        project_brain.update_agent_work_status(p['id'], 'Codey', 'completed', 'Signup flow is done, using OTP auth.')
        ctx = project_brain.project_context(project_brain.get_project(p['id']), 'marketer', 'Write launch copy', agent_name='Mira')
        self.assertIn('Legal-only detail', ctx)
        self.assertIn('Signup flow is done', ctx)
        self.assertIn('full sharing', ctx)

    def test_full_share_project_card_shows_all_summaries_to_every_viewer(self):
        p = project_brain.create_project('App', 'Build an app', 'app')
        project_brain.set_share_mode(p['id'], 'full')
        coder = {'id': 'a1', 'name': 'Codey', 'role': 'coder'}
        marketer = {'id': 'a2', 'name': 'Mira', 'role': 'marketer'}
        project_brain.set_agent_work(p['id'], coder, 'Build the signup flow')
        project_brain.set_agent_work(p['id'], marketer, 'Write launch copy')
        project_brain.record_worker_result(p['id'], 'Codey', 'coder', 'Build the signup flow', 'Shipped OTP-based signup.')
        card = project_brain.project_card(project_brain.get_project(p['id']), viewer_agent_id='a2')
        self.assertTrue(any('Shipped OTP-based signup.' in s for s in card['summaries']))

    def test_scope_command_reverts_to_scoped(self):
        p = project_brain.create_project('App', 'Build an app', 'app')
        project_brain.set_share_mode(p['id'], 'full')
        result = project_brain.route_project_command(f"make project {p['name']} scoped")
        self.assertEqual(result['card']['share_mode'], 'scoped')


if __name__ == '__main__':
    unittest.main()
