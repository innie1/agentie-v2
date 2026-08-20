import unittest
from pathlib import Path


class UIUpgradeRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui=Path('frontend/ui_upgrade.js').read_text(encoding='utf-8')
        cls.main=Path('main.py').read_text(encoding='utf-8')

    def test_ui_upgrade_is_served_and_loaded(self):
        self.assertIn('UI_UPGRADE_JS=FRONTEND_DIR/"ui_upgrade.js"',self.main)
        self.assertIn('<script src="/ui-upgrade.js?v=202"></script>',self.main)
        self.assertIn('@app.get("/ui-upgrade.js")',self.main)

    def test_sidebar_is_fixed_and_chat_scrolls_independently(self):
        self.assertIn('html,body{height:100%;overflow:hidden}',self.ui)
        self.assertIn('.sidebar{height:100vh',self.ui)
        self.assertIn('.chat-shell{height:100vh;min-width:0;overflow-y:auto',self.ui)

    def test_collapsed_sidebar_keeps_agent_orbs(self):
        self.assertIn('.app-shell.sidebar-collapsed{grid-template-columns:64px 1fr}',self.ui)
        self.assertIn('.sidebar.collapsed .agent-copy',self.ui)
        self.assertIn('.sidebar.collapsed .agent-orb{width:38px;height:38px}',self.ui)

    def test_search_and_removed_subtitle_are_wired(self):
        self.assertIn("document.querySelector('.subtle')?.remove()",self.ui)
        self.assertIn("search.placeholder='Search agents'",self.ui)
        self.assertIn("search.addEventListener('input'",self.ui)

    def test_jobs_render_as_native_cards_not_json(self):
        self.assertIn("if(c?.type==='jobs')return renderJobs(c)",self.ui)
        self.assertIn("if(c?.type==='job_progress')return renderJob(c)",self.ui)
        self.assertIn('job-step',self.ui)
        self.assertNotIn('JSON.stringify(c,null,2)',self.ui)

    def test_agent_instructions_render_as_native_card(self):
        self.assertIn("if(c?.type==='agent_instructions')return renderInstructions(c)",self.ui)
        self.assertIn('View generated system prompt',self.ui)
        self.assertIn('Learned preferences',self.ui)


if __name__=='__main__':unittest.main()
