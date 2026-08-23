import unittest
from pathlib import Path


class GroupChatInstantOpenRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guard = Path("frontend/group_chat_instant_open.js").read_text(encoding="utf-8")
        cls.api = Path("agentie/core/platform_next4_api.py").read_text(encoding="utf-8")

    def test_group_open_is_hidden_until_latest_position_is_ready(self):
        src = self.guard
        for marker in (
            "__agentieGroupInstantOpenGuard",
            "#persistentAgentList .sidebar-group-row",
            "messages.style.visibility='hidden'",
            "messages.style.minHeight=",
            "MutationObserver",
            "agentie-connected-group-opening",
            "setLatest(root)",
            "messages.style.visibility=''",
            "focus({preventScroll:true})",
        ):
            self.assertIn(marker, src)
        self.assertLess(src.index("setLatest(root)"), src.index("messages.style.visibility=''"))

    def test_open_guard_runs_before_document_group_handler_and_uses_real_scroll_root(self):
        src = self.guard
        self.assertIn("window.addEventListener('pointerdown'", src)
        self.assertNotIn("document.addEventListener('pointerdown',event", src)
        self.assertIn("document.querySelector('.chat-shell')", src)
        self.assertIn("document.scrollingElement||document.documentElement||document.body", src)
        self.assertIn("getComputedStyle(shell)", src)
        self.assertIn("shell.scrollHeight>shell.clientHeight+1", src)
        self.assertIn("root.scrollTop=root.scrollHeight", src)
        self.assertNotIn("behavior:'smooth'", src)

    def test_reveal_waits_until_navigation_bottom_positioning_frame(self):
        src = self.guard
        self.assertIn("let revealFrame=0", src)
        self.assertIn("revealFrame=requestAnimationFrame(()=>finishOpen(messages,token))", src)
        self.assertIn("navigation_connect schedules its own bottom positioning", src)
        self.assertIn("cancelAnimationFrame(revealFrame)", src)

    def test_guard_does_not_own_or_duplicate_group_backend_runtime(self):
        src = self.guard
        self.assertNotIn("/platform/agent-chats", src)
        self.assertNotIn("setInterval(refreshGroup", src)
        self.assertNotIn("fetch(", src)
        self.assertIn("navigation_connect owns the group runtime", src)

    def test_guard_is_bundled_after_navigation_controller(self):
        bundle='"navigation_connect.js", "group_chat_instant_open.js"'
        self.assertIn(bundle, self.api)
        self.assertIn('@router.get("/platform-group-instant-open.js")', self.api)


if __name__ == "__main__":
    unittest.main()
