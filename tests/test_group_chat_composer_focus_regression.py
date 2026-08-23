import asyncio
import unittest
from pathlib import Path

import main


class GroupChatComposerFocusRegressionTests(unittest.TestCase):
    def test_live_chat_bundle_contains_composer_focus_guard(self):
        routes=[r for r in main.app.routes if getattr(r,'path',None)=='/platform-next4.js']
        self.assertEqual(len(routes),1)
        text=asyncio.run(routes[0].endpoint()).body.decode('utf-8')
        self.assertIn('__agentieChatComposerFocusGuard',text)
        self.assertIn('Message or task',text)
        self.assertIn('MutationObserver',text)
        self.assertIn("ta.focus({preventScroll:true})",text)
        self.assertIn('setSelectionRange',text)
        self.assertIn('__agentieGroupOfflineCache',text)
        self.assertIn('__agentieNavigationConnect',text)
        self.assertIn('__agentieGroupInstantOpenGuard',text)
        self.assertIn('__agentieCreateMenuLoader',text)
        self.assertNotIn('__agentieCreateMenu=true',text)

    def test_focus_guard_preserves_draft_across_dom_replacement(self):
        text=Path('frontend/platform_chat_focus_guard.js').read_text(encoding='utf-8')
        for marker in (
            "s.value=ta.value",
            "s.start=ta.selectionStart",
            "s.focused=true",
            "if(next&&!isComposer(next)",
            "if(!s?.focused||!modal.isConnected)return",
            "ta.value=s.value",
            "requestAnimationFrame",
        ):
            self.assertIn(marker,text)

    def test_focus_guard_is_bundled_before_navigation_and_only_small_create_loader_is_startup_loaded(self):
        source=Path('agentie/core/platform_next4_api.py').read_text(encoding='utf-8')
        bundle='_frontend_bundle("platform_next4.js", "platform_chat_focus_guard.js", "group_chat_markdown.js", "model_router.js", "group_chat_offline_cache.js", "navigation_connect.js", "group_chat_instant_open.js", "create_menu_loader.js")'
        self.assertIn(bundle,source)
        self.assertLess(bundle.index('platform_next4.js'),bundle.index('platform_chat_focus_guard.js'))
        self.assertLess(bundle.index('model_router.js'),bundle.index('group_chat_offline_cache.js'))
        self.assertLess(bundle.index('group_chat_offline_cache.js'),bundle.index('navigation_connect.js'))
        self.assertLess(bundle.index('navigation_connect.js'),bundle.index('group_chat_instant_open.js'))
        self.assertLess(bundle.index('group_chat_instant_open.js'),bundle.index('create_menu_loader.js'))
        self.assertNotIn('"group_chat_instant_open.js", "create_menu.js")',source)
        self.assertIn('group_chat_markdown.js',bundle)
        self.assertIn('@router.get("/platform-chat-focus-guard.js")',source)
        self.assertIn('@router.get("/platform-group-chat-offline-cache.js")',source)
        self.assertIn('@router.get("/platform-navigation-connect.js")',source)
        self.assertIn('@router.get("/platform-group-instant-open.js")',source)
        self.assertIn('@router.get("/platform-create-menu.js")',source)


if __name__=='__main__':
    unittest.main()
