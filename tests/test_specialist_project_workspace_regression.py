import re
import unittest
from pathlib import Path


class SpecialistProjectWorkspaceRegressionTests(unittest.TestCase):
    def test_workspace_component_is_loaded_from_existing_ui_upgrade_bundle(self):
        main=Path('main.py').read_text(encoding='utf-8')
        self.assertIn('(FRONTEND_DIR/"project_workspace.js").read_text',main)
        self.assertRegex(main,r'/ui-upgrade\.js\?v=\d+')

    def test_assigned_project_preview_is_compact_and_markdown_free(self):
        raw=Path('frontend/project_workspace.js').read_text(encoding='utf-8')
        self.assertIn('workspace-preview-task',raw)
        self.assertIn('workspace-preview-summary',raw)
        self.assertIn('cleanPreview',raw)
        self.assertIn('previewTitle',raw)
        self.assertIn("replace(/^#{1,6}\\s*/gm,'')",raw)
        self.assertIn("replace(/\\*\\*([^*]+)\\*\\*/g,'$1')",raw)
        self.assertIn("strong.textContent=title||'Completed result'",raw)
        self.assertIn('-webkit-line-clamp:2',raw)

    def test_active_agent_lookup_ignores_role_badge_text(self):
        raw=Path('frontend/project_workspace.js').read_text(encoding='utf-8')
        self.assertIn("strong?.childNodes?.[0]?.textContent?.trim()",raw)
        self.assertIn("find(a=>a.name===name)",raw)

    def test_open_uses_scoped_agent_project_not_global_project(self):
        raw=Path('frontend/project_workspace.js').read_text(encoding='utf-8')
        self.assertIn('Show projects for ${agent.name}',raw)
        self.assertIn('ui:project-workspace:${agent.id}',raw)
        self.assertNotIn('Show project ${id}',raw)
        self.assertNotIn('Show project ${project.id}',raw)
        self.assertIn('window.AgentieProjectWorkspace={open:openWorkspace,activeAgent}',raw)

    def test_open_click_is_captured_before_older_project_handler(self):
        raw=Path('frontend/project_workspace.js').read_text(encoding='utf-8')
        self.assertIn("messages.addEventListener('click'",raw)
        self.assertIn("button.textContent.trim()!=='Open'",raw)
        self.assertIn("button.closest('.agent-projects-pinned .project-list-row')",raw)
        self.assertIn('e.stopImmediatePropagation()',raw)
        self.assertIn('openWorkspace(button)',raw)
        self.assertIn('},true);',raw)
        self.assertIn("button.textContent='Opening…'",raw)

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

    def test_project_preview_observer_cannot_self_trigger_forever(self):
        raw=Path('frontend/project_workspace.js').read_text(encoding='utf-8')
        self.assertIn("if(result&&!result.dataset.workspacePreview)",raw)
        self.assertIn("result.dataset.workspacePreview='1'",raw)
        self.assertIn('let polishQueued=false',raw)
        self.assertIn('requestAnimationFrame(()=>{polishQueued=false;polish()})',raw)
        self.assertNotIn('setInterval(polish,1200)',raw)


if __name__=='__main__':
    unittest.main()