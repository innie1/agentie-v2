import unittest
from pathlib import Path


class GroupChatOfflineRetentionRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cache = Path('frontend/group_chat_offline_cache.js').read_text(encoding='utf-8')
        cls.api = Path('agentie/core/platform_next4_api.py').read_text(encoding='utf-8')
        cls.instant = Path('frontend/group_chat_instant_open.js').read_text(encoding='utf-8')

    def test_group_snapshots_are_persisted_in_browser_storage(self):
        src = self.cache
        for marker in (
            "agentie.groupchat.cache.v1:",
            "localStorage.setItem",
            "localStorage.getItem",
            "threadKey(value.id)",
            "window.__agentieGroupCacheRead",
            "window.__agentieGroupCacheList",
        ):
            self.assertIn(marker, src)

    def test_failed_local_get_uses_saved_thread_instead_of_empty_red_screen(self):
        src = self.cache
        self.assertIn("if(method!=='GET')return null", src)
        self.assertIn("const cached=fallback(path,method)", src)
        self.assertIn("if(cached)return cached", src)
        self.assertIn("new Response(JSON.stringify(value)", src)
        self.assertIn("X-Agentie-Group-Cache", src)

    def test_successful_group_list_primes_each_thread_for_future_offline_open(self):
        src = self.cache
        self.assertIn("for(const item of data.items||[])primeThread(item?.id)", src)
        self.assertIn("async function primeThread(id)", src)
        self.assertIn("/platform/agent-chats/${encodeURIComponent(id)}", src)
        self.assertIn("saveThread(data)", src)

    def test_cache_loads_before_single_visible_group_controller_and_create_menu_loads_last(self):
        bundle='_frontend_bundle("platform_next4.js", "platform_chat_focus_guard.js", "group_chat_markdown.js", "model_router.js", "group_chat_offline_cache.js", "navigation_connect.js", "group_chat_instant_open.js", "create_menu.js")'
        self.assertIn(bundle, self.api)
        self.assertLess(bundle.index('group_chat_offline_cache.js'), bundle.index('navigation_connect.js'))
        self.assertLess(bundle.index('group_chat_instant_open.js'), bundle.index('create_menu.js'))
        self.assertIn('@router.get("/platform-group-chat-offline-cache.js")', self.api)

    def test_instant_open_uses_real_chat_scroll_container(self):
        self.assertIn("document.querySelector('.chat-shell')", self.instant)
        self.assertIn("root.scrollTop=root.scrollHeight", self.instant)
        self.assertIn("messages.style.visibility='hidden'", self.instant)
        self.assertIn("messages.style.visibility=''", self.instant)


if __name__ == '__main__':
    unittest.main()
