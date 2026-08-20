import asyncio
import unittest
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
        self.assertEqual(proposal['card']['actions'][0]['label'],'Use Computer')
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
            with patch.object(browser_monitor,'_launch_computer_fallback',new=AsyncMock(return_value={'message':'ready','card':{'type':'computer_fallback'}})) as launch:
                result=await browser_monitor.route_browser_request('Use Computer for: Post our launch update on X')
                launch.assert_awaited_once_with('Post our launch update on X')
                return result
        result=asyncio.run(scenario())
        self.assertEqual(result['card']['type'],'computer_fallback')

    def test_normal_non_service_conversation_is_not_intercepted(self):
        with patch.object(browser_monitor,'_connected_plugin_names',return_value=set()):
            self.assertIsNone(browser_monitor._service_for_task('Explain our launch strategy'))


if __name__=='__main__':unittest.main()
