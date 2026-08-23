import unittest
from pathlib import Path


class NavigationRewireConnectedRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("frontend/group_chat_markdown.js").read_text(encoding="utf-8")

    def test_profile_uses_real_activity_and_automation_launchers(self):
        src = self.source
        self.assertIn("__agentieNavigationRewire", src)
        self.assertIn("profile.querySelector('.platform-activity-launch')", src)
        self.assertIn("profile.querySelector('.n4-auto,.pa-automation-launch')", src)
        self.assertIn("profile.querySelector('[data-profile-action=\"activity\"]')?.remove()", src)
        self.assertIn("profile.querySelector('[data-profile-action=\"automation\"]')?.remove()", src)
        self.assertIn("profile.appendChild(activity)", src)
        self.assertIn("profile.appendChild(automation)", src)
        self.assertIn("agentie-profile-real-action", src)

    def test_skills_and_marketplace_are_moved_inside_plugins(self):
        src = self.source
        self.assertIn("#agentiePluginsPanel .plugins-body", src)
        self.assertIn("agentie-plugin-tools", src)
        self.assertIn("tools.querySelector('.platform-skills-launch')", src)
        self.assertIn("tools.querySelector('.n4-market')", src)
        self.assertIn("tools.appendChild(skills)", src)
        self.assertIn("tools.appendChild(market)", src)
        self.assertIn("Skills & marketplace", src)
        self.assertIn(".sidebar>.n4-market", src)
        self.assertIn(".sidebar>.platform-skills-launch", src)

    def test_at_activity_and_automation_invoke_moved_real_actions(self):
        src = self.source
        self.assertIn("function clickMovedAction", src)
        self.assertIn(".agentie-profile-menu .platform-activity-launch", src)
        self.assertIn(".agentie-profile-menu .n4-auto,.agentie-profile-menu .pa-automation-launch", src)
        self.assertIn("lower==='activity'||lower==='automation'", src)

    def test_group_row_opens_real_thread_in_main_chat(self):
        src = self.source
        self.assertIn("#persistentAgentList .sidebar-group-row", src)
        self.assertIn("openGroup(row.dataset.groupId)", src)
        self.assertIn("/platform/agent-chats/${encodeURIComponent(id)}", src)
        self.assertIn("document.getElementById('messages')", src)
        self.assertIn("row.className=isUser?'user-row':'assistant-row'", src)
        self.assertIn("bubble.className='bubble '+(isUser?'user':'assistant')", src)
        self.assertIn("window.__agentieOpenGroupChat=openGroup", src)

    def test_normal_composer_posts_to_active_group_backend(self):
        src = self.source
        self.assertIn("#sendButton", src)
        self.assertIn("e.target?.id!=='messageInput'", src)
        self.assertIn("window.__agentieSendActiveGroupMessage=sendGroup", src)
        self.assertIn("/platform/agent-chats/${encodeURIComponent(state.group.id)}/messages", src)
        self.assertIn("method:'POST'", src)
        self.assertIn("JSON.stringify({message:value})", src)


if __name__ == "__main__":
    unittest.main()
