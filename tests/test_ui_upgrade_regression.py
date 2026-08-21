import re
import unittest
from pathlib import Path

class UIUpgradeRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui=Path('frontend/ui_upgrade.js').read_text(encoding='utf-8')
        cls.main=Path('main.py').read_text(encoding='utf-8')

    def test_ui_upgrade_is_served_and_loaded(self):
        self.assertIn('UI_UPGRADE_JS=FRONTEND_DIR/"ui_upgrade.js"',self.main)
        self.assertRegex(self.main,r'<script src="/ui-upgrade\.js\?v=\d+"></script>')
        self.assertIn('@app.get("/ui-upgrade.js")',self.main)

    def test_sidebar_is_fixed_wider_and_chat_scrolls_independently(self):
        self.assertIn('html,body{height:100%;overflow:hidden}',self.ui)
        self.assertIn('grid-template-columns:248px minmax(0,1fr) 0',self.ui)
        self.assertIn('.sidebar{height:100vh',self.ui)
        self.assertIn('.chat-shell{height:100vh;min-width:0;overflow-y:auto',self.ui)

    def test_collapsed_sidebar_keeps_agent_orbs_without_brand_a(self):
        self.assertIn('.app-shell.sidebar-collapsed{grid-template-columns:64px minmax(0,1fr) 0}',self.ui)
        self.assertIn('.sidebar.collapsed .brand{display:none}',self.ui)
        self.assertIn('.sidebar.collapsed .agent-orb{width:38px;height:38px}',self.ui)
        self.assertNotIn(".brand:after{content:'A'",self.ui)

    def test_search_plus_create_agent_and_removed_subtitle_are_wired(self):
        self.assertIn("document.querySelector('.subtle')?.remove()",self.ui)
        self.assertIn("search.placeholder='Search agents'",self.ui)
        self.assertIn("plus.title='Create agent'",self.ui)
        self.assertIn('Create an agent called ${name.trim()}',self.ui)

    def test_top_agent_head_opens_existing_agent_menu_not_chat_instructions(self):
        self.assertIn('workspace-topbar',self.ui)
        self.assertIn('top-agent-orb',self.ui)
        self.assertIn("row?.querySelector('.agent-edit')",self.ui)
        self.assertIn('edit.click()',self.ui)
        self.assertNotIn('dispatchChat(`Show ${a.name} instructions`)',self.ui)

    def test_composer_switches_from_microphone_to_send_arrow(self):
        self.assertIn(".composer button::before{content:'🎙'",self.ui)
        self.assertIn(".composer.has-text button::before{content:'➤'",self.ui)
        self.assertIn("classList.toggle('has-text'",self.ui)
        self.assertIn('background:#0b84ff!important',self.ui)

    def test_right_routines_panel_matches_sidebar_and_resizes_composer(self):
        self.assertIn('.app-shell.right-open{grid-template-columns:248px minmax(0,1fr) 248px}',self.ui)
        self.assertIn('.app-shell.right-open .composer-wrap{right:248px!important}',self.ui)
        self.assertIn("right.className='right-panel'",self.ui)
        self.assertIn("message:'Show routines'",self.ui)
        self.assertIn('Create routine',self.ui)

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
