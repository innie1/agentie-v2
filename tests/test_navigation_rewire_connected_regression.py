import unittest
from pathlib import Path


class NavigationRewireConnectedRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("frontend/navigation_connect.js").read_text(encoding="utf-8")

    def test_profile_menu_is_real_and_connected(self):
        src = self.source
        self.assertIn("__agentieNavigationConnect", src)
        self.assertIn("agentie-connected-profile-menu", src)
        self.assertIn('data-connected-profile="settings"', src)
        self.assertIn('data-connected-profile="activity"', src)
        self.assertIn('data-connected-profile="automation"', src)
        self.assertIn("invokeNative('activity')", src)
        self.assertIn("invokeNative('automation')", src)
        self.assertIn("bottom:calc(100% + 6px)", src)

    def test_ai_model_is_opened_from_profile_settings(self):
        src = self.source
        self.assertIn("function openSettings()", src)
        self.assertIn("data-model-slot", src)
        self.assertIn("__agentieMountModelRouter", src)

    def test_skills_and_marketplace_live_inside_plugins_without_body_reload_race(self):
        src = self.source
        self.assertIn("agentie-connected-plugin-tools", src)
        self.assertIn('data-plugin-tool="skills"', src)
        self.assertIn('data-plugin-tool="marketplace"', src)
        self.assertIn("head.insertAdjacentElement('afterend',tools)", src)
        self.assertIn("invokeNative('skills')", src)
        self.assertIn("invokeNative('marketplace')", src)
        self.assertIn(".sidebar>.platform-skills-launch", src)
        self.assertIn(".sidebar>.n4-market", src)

    def test_group_row_opens_real_thread_in_normal_main_chat(self):
        src = self.source
        self.assertIn("#persistentAgentList .sidebar-group-row", src)
        self.assertIn("document.addEventListener('pointerdown'", src)
        self.assertIn("state.lastPointerGroup=id", src)
        self.assertIn("openGroup(id)", src)
        self.assertIn("showOpeningGroup(id)", src)
        self.assertIn("Opening group chat…", src)
        self.assertIn("Could not open group chat:", src)
        self.assertIn("/platform/agent-chats/${encodeURIComponent(id)}", src)
        self.assertIn("document.getElementById('messages')", src)
        self.assertIn("row.className=isUser?'user-row':'assistant-row'", src)
        self.assertIn("bubble.className='bubble '+(isUser?'user':'assistant')", src)
        self.assertIn("window.__agentieOpenGroupChat=openGroup", src)

    def test_normal_composer_posts_to_active_group_backend(self):
        src = self.source
        self.assertIn("function wireComposer()", src)
        self.assertIn("send.addEventListener('click'", src)
        self.assertIn("input.addEventListener('keydown'", src)
        self.assertIn("window.__agentieSendActiveGroupMessage=sendGroup", src)
        self.assertIn("/platform/agent-chats/${encodeURIComponent(state.group.id)}/messages", src)
        self.assertIn("JSON.stringify({message:value})", src)

    def test_group_polling_respects_manual_scroll_up(self):
        src = self.source
        self.assertIn("function scrollHost(){return document.querySelector('.chat-shell')}", src)
        self.assertIn("function isNearBottom", src)
        self.assertIn("followBottom:true", src)
        self.assertIn("if(!state.group||state.restoringScroll)return", src)
        self.assertIn("state.followBottom=isNearBottom(host,120)", src)
        self.assertIn("else setHostScroll(host,oldTop)", src)
        self.assertNotIn("document.documentElement.scrollHeight-window.scrollY-window.innerHeight", src)
        self.assertNotIn("window.scrollTo({top:document.body.scrollHeight", src)

    def test_group_identity_replaces_single_agent_topbar_while_active(self):
        src = self.source
        self.assertIn("function syncTopbar", src)
        self.assertIn(".workspace-topbar .top-agent", src)
        self.assertIn("agentie-connected-top-group", src)
        self.assertIn("agentie-connected-top-participants", src)
        self.assertIn("title.textContent=d.name||'Group chat'", src)
        self.assertIn("for(const name of d.participants||[])", src)
        self.assertIn("orb.style.setProperty('display','none','important')", src)
        self.assertIn("syncTopbar(null)", src)


if __name__ == "__main__":
    unittest.main()
