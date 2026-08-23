import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agentie.core import browser_monitor


class ComputerFallbackRegressionTests(unittest.TestCase):
    def test_external_task_without_plugin_proposes_computer(self):
        with patch.object(browser_monitor,'_connected_plugin_names',return_value=set()):
            item=browser_monitor._service_for_task('Post our launch update on X')
        self.assertIsNotNone(item)
        self.assertEqual(item['service'],'x')
        self.assertTrue(item['consequential'])
        proposal=browser_monitor._fallback_proposal('Post our launch update on X',item)
        self.assertEqual(proposal['card']['type'],'computer_fallback_proposal')
        self.assertEqual([x['label'] for x in proposal['card']['actions']],['Use Computer','Keep in chat'])

    def test_connected_service_plugin_prevents_computer_proposal(self):
        with patch.object(browser_monitor,'_connected_plugin_names',return_value={'x'}):
            self.assertIsNone(browser_monitor._service_for_task('Post our launch update on X'))

    def test_gmail_task_maps_to_gmail_computer_target(self):
        with patch.object(browser_monitor,'_connected_plugin_names',return_value=set()):
            item=browser_monitor._service_for_task('Read my Gmail inbox')
        self.assertEqual(item['service'],'gmail')
        self.assertEqual(item['url'],'https://mail.google.com')
        self.assertFalse(item['consequential'])

    def test_use_computer_command_uses_qemu_fallback_executor_and_session(self):
        async def scenario():
            with patch.object(browser_monitor,'_launch_computer_fallback',new=AsyncMock(return_value={'message':'ready','card':{'type':'desktop_view','mode':'qemu'}})) as launch:
                result=await browser_monitor.route_browser_request('Use Computer for: Post our launch update on X','agent:agt_sales:main')
                launch.assert_awaited_once_with('Post our launch update on X','agent:agt_sales:main')
                return result
        result=asyncio.run(scenario())
        self.assertEqual(result['card']['mode'],'qemu')

    def test_fallback_card_uses_shared_qemu_display(self):
        info={'computer_id':'company-default','state':'AGENT_CONTROL','running':True,'display_url':'http://127.0.0.1:6088/vnc.html?view_only=1','display_ready':True,'browser_ready':False,'acceleration':{'accelerator':'kvm'},'profile':{'vm_ram_mb':1024,'vm_vcpus':1}}
        candidate={'service':'gmail','url':'https://mail.google.com','task':'Read my Gmail inbox','consequential':False}
        card=browser_monitor._desktop_fallback_card(info,candidate,candidate['task'])
        self.assertEqual(card['mode'],'qemu')
        self.assertEqual(card['computer_id'],'company-default')
        self.assertIn('6088',card['display_url'])
        self.assertNotIn('kasmvnc_url',card)

    def test_fallback_ui_is_native_not_raw_json(self):
        text=Path('frontend/ui_upgrade.js').read_text(encoding='utf-8')
        self.assertIn('computer_fallback_proposal',text)
        self.assertIn('Use Computer',text)
        self.assertIn('Keep in chat',text)

    def test_old_desktop_stack_is_not_used_by_browser_monitor(self):
        text=Path('agentie/core/browser_monitor.py').read_text(encoding='utf-8').lower()
        for obsolete in ('wsl_desktop','kasmvnc','xfce4-notifyd','8444'):
            self.assertNotIn(obsolete,text)

    def test_normal_non_service_conversation_is_not_intercepted(self):
        with patch.object(browser_monitor,'_connected_plugin_names',return_value=set()):
            self.assertIsNone(browser_monitor._service_for_task('Explain our launch strategy'))


if __name__=='__main__':unittest.main()
