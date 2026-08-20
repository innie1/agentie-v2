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
        self.assertTrue(proposal['card']['actions'][0]['command'].startswith('Use Computer for:'))

    def test_connected_service_plugin_prevents_computer_proposal(self):
        with patch.object(browser_monitor,'_connected_plugin_names',return_value={'x'}):
            item=browser_monitor._service_for_task('Post our launch update on X')
        self.assertIsNone(item)

    def test_gmail_task_maps_to_gmail_computer_target(self):
        with patch.object(browser_monitor,'_connected_plugin_names',return_value=set()):
            item=browser_monitor._service_for_task('Read my Gmail inbox')
        self.assertEqual(item['service'],'gmail')
        self.assertEqual(item['url'],'https://mail.google.com')
        self.assertFalse(item['consequential'])

    def test_use_computer_command_uses_existing_fallback_executor(self):
        async def scenario():
            with patch.object(browser_monitor,'_launch_computer_fallback',new=AsyncMock(return_value={'message':'ready','card':{'type':'desktop_view','mode':'wsl'}})) as launch:
                result=await browser_monitor.route_browser_request('Use Computer for: Post our launch update on X')
                launch.assert_awaited_once_with('Post our launch update on X')
                return result
        result=asyncio.run(scenario())
        self.assertEqual(result['card']['type'],'desktop_view')
        self.assertEqual(result['card']['mode'],'wsl')

    def test_fallback_launch_returns_existing_desktop_card_without_waiting_for_cdp(self):
        async def scenario():
            info={'running':True,'novnc_url':'http://127.0.0.1:8444/','kasmvnc_url':'http://127.0.0.1:8444/','chrome_ready':False,'distro':'Ubuntu'}
            with patch('agentie.core.wsl_desktop.ensure_started',return_value=info), patch('agentie.core.wsl_desktop._run_wsl'):
                return await browser_monitor._launch_computer_fallback('Read my Gmail inbox')
        result=asyncio.run(scenario())
        self.assertEqual(result['card']['type'],'desktop_view')
        self.assertEqual(result['card']['fallback_service'],'gmail')
        self.assertEqual(result['card']['novnc_url'],'http://127.0.0.1:8444/')

    def test_fallback_ui_is_native_not_raw_json(self):
        text=Path('frontend/ui_upgrade.js').read_text(encoding='utf-8')
        self.assertIn("computer_fallback_proposal",text)
        self.assertIn("Use Computer",text)
        self.assertIn("Keep in chat",text)
        self.assertIn("renderComputerFallbackProposal",text)

    def test_notification_daemon_is_suppressed_during_fallback_start(self):
        text=Path('agentie/core/browser_monitor.py').read_text(encoding='utf-8')
        self.assertIn('xfce4-notifyd',text)
        self.assertIn('pkill',text)

    def test_normal_non_service_conversation_is_not_intercepted(self):
        with patch.object(browser_monitor,'_connected_plugin_names',return_value=set()):
            self.assertIsNone(browser_monitor._service_for_task('Explain our launch strategy'))


if __name__=='__main__':unittest.main()
