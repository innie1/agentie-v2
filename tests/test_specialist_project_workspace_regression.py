import unittest
from pathlib import Path


class SpecialistProjectWorkspaceRegressionTests(unittest.TestCase):
    def test_workspace_component_is_loaded_from_existing_ui_upgrade_bundle(self):
        main=Path('main.py').read_text(encoding='utf-8')
        self.assertIn('(FRONTEND_DIR/"project_workspace.js").read_text',main)
        self.assertIn('/ui-upgrade.js?v=203',main)

    def test_assigned_project_preview_is_compact(self):
        raw=Path('frontend/project_workspace.js').read_text(encoding='utf-8')
        self.assertIn('workspace-preview-task',raw)
        self.assertIn('workspace-preview-summary',raw)
        self.assertIn('slice(0,180)',raw)
        self.assertIn('-webkit-line-clamp:2',raw)

    def test_open_uses_scoped_agent_project_not_global_project(self):
        raw=Path('frontend/project_workspace.js').read_text(encoding='utf-8')
        self.assertIn('Show projects for ${agent.name}',raw)
        self.assertIn('ui:project-workspace:${agent.id}',raw)
        self.assertNotIn('Show project ${id}',raw)
        self.assertNotIn('Show project ${project.id}',raw)

    def test_full_result_comes_from_that_agents_handoff_history(self):
        raw=Path('frontend/project_workspace.js').read_text(encoding='utf-8')
        self.assertIn('/handoff-chat',raw)
        self.assertIn("x.role==='assistant'",raw)
        self.assertIn('x.team_job_id===work.team_job_id',raw)
        self.assertIn('x.project_id===project.id',raw)

    def test_workspace_renders_markdown_structure_and_artifacts(self):
        raw=Path('frontend/project_workspace.js').read_text(encoding='utf-8')
        self.assertIn('specialist-markdown',raw)
        self.assertIn("document.createElement('table')",raw)
        self.assertIn("document.createElement('pre')",raw)
        self.assertIn("document.createElement(`h${hm[1].length}`)",raw)
        self.assertIn("section(el,'Your work')",raw)
        self.assertIn("section(el,'Artifacts')",raw)
        self.assertIn('project.artifacts||[]',raw)

    def test_workspace_shows_only_scoped_context_fields(self):
        raw=Path('frontend/project_workspace.js').read_text(encoding='utf-8')
        self.assertIn("contextItem('Relevant decisions',project.decisions)",raw)
        self.assertIn("contextItem('Relevant context',project.context)",raw)
        self.assertIn("contextItem('Milestones',project.milestones)",raw)
        self.assertNotIn('assigned_agents',raw)
        self.assertNotIn('specialists',raw)


if __name__=='__main__':
    unittest.main()
