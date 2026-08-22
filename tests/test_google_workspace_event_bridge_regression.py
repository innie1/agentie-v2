import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch

from agentie.core import automation_events,google_workspace_events,platform_router


class GoogleWorkspaceEventBridgeRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);root=Path(self.temp.name)
        self.patches=[patch.object(google_workspace_events,'WORKSPACE',root),patch.object(google_workspace_events,'STATE_FILE',root/'google_workspace_events.json'),patch.object(automation_events,'WORKSPACE',root),patch.object(automation_events,'EVENTS',root/'automation_events.json')]
        for p in self.patches:p.start()

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def _info(self,*names):return {'tools':[{'name':x,'description':'read-only test tool','input_schema':{}} for x in names]}
    def _result(self,value):return {'message':'ok','card':{'type':'note','title':'Google','content':json.dumps(value)}}

    def test_disabled_sources_do_not_touch_google_mcp(self):
        with patch.object(google_workspace_events,'_inspect',new=AsyncMock()) as inspect:
            result=asyncio.run(google_workspace_events.poll_enabled_sources())
        self.assertFalse(result['polled']);inspect.assert_not_awaited()

    def test_gmail_first_poll_is_baseline_then_new_message_emits_once(self):
        google_workspace_events.update_settings(gmail_enabled=True)
        first=self._result({'messages':[{'id':'m1','subject':'Old'}]});second=self._result({'messages':[{'id':'m2','subject':'New'},{'id':'m1','subject':'Old'}]})
        with patch.object(google_workspace_events,'get_server',return_value={'name':'google-workspace'}),patch.object(google_workspace_events,'inspect_server',new=AsyncMock(return_value=self._info('searchEmails'))),patch.object(google_workspace_events,'execute_tool',new=AsyncMock(side_effect=[first,second,second])) as execute:
            a=asyncio.run(google_workspace_events.poll_enabled_sources());b=asyncio.run(google_workspace_events.poll_enabled_sources());c=asyncio.run(google_workspace_events.poll_enabled_sources())
        self.assertEqual(a['events'],0);self.assertEqual(b['events'],1);self.assertEqual(c['events'],0)
        events=automation_events.recent_events();self.assertEqual(len(events),1);self.assertEqual(events[0]['type'],'email.received');self.assertEqual(events[0]['payload']['id'],'m2')
        args=execute.await_args_list[0].args;self.assertEqual(args[0],'google-workspace');self.assertEqual(args[1],'searchEmails');self.assertIn('newer_than',args[2]['query'])

    def test_calendar_uses_read_only_discovered_tool_and_emits_only_new_event(self):
        google_workspace_events.update_settings(calendar_enabled=True)
        old=self._result({'events':[{'id':'e1','summary':'Existing'}]});new=self._result({'events':[{'id':'e2','summary':'Starting now'},{'id':'e1'}]})
        with patch.object(google_workspace_events,'get_server',return_value={'name':'google-workspace'}),patch.object(google_workspace_events,'inspect_server',new=AsyncMock(return_value=self._info('listEvents'))),patch.object(google_workspace_events,'execute_tool',new=AsyncMock(side_effect=[old,new])) as execute:
            asyncio.run(google_workspace_events.poll_enabled_sources());out=asyncio.run(google_workspace_events.poll_enabled_sources())
        self.assertEqual(out['events'],1);event=automation_events.recent_events()[0];self.assertEqual(event['type'],'calendar.event.started');self.assertEqual(event['payload']['id'],'e2')
        self.assertEqual(execute.await_args_list[0].args[1],'listEvents');self.assertEqual(execute.await_args_list[0].args[2]['calendarId'],'primary')

    def test_drive_requires_explicit_watch_baselines_then_emits_change(self):
        watch=google_workspace_events.add_drive_watch('file123',kind='file',label='Budget');before=self._result({'id':'file123','modifiedTime':'1'});after=self._result({'id':'file123','modifiedTime':'2'})
        with patch.object(google_workspace_events,'get_server',return_value={'name':'google-workspace'}),patch.object(google_workspace_events,'inspect_server',new=AsyncMock(return_value=self._info('getFileMetadata'))),patch.object(google_workspace_events,'execute_tool',new=AsyncMock(side_effect=[before,after])) as execute:
            first=asyncio.run(google_workspace_events.poll_enabled_sources());second=asyncio.run(google_workspace_events.poll_enabled_sources())
        self.assertEqual(first['events'],0);self.assertEqual(second['events'],1);event=automation_events.recent_events()[0];self.assertEqual(event['type'],'drive.file.changed');self.assertEqual(event['payload']['watch_id'],watch['id']);self.assertEqual(execute.await_args_list[0].args[1],'getFileMetadata')

    def test_status_never_claims_connection_without_real_inspection(self):
        with patch.object(google_workspace_events,'get_server',return_value=None),patch.object(google_workspace_events,'inspect_server',new=AsyncMock()) as inspect,patch.object(google_workspace_events,'public_setup_state',return_value={'configured':False}):
            status=asyncio.run(google_workspace_events.bridge_status(verify_connection=True))
        self.assertFalse(status['registered']);self.assertIsNone(status['connected']);inspect.assert_not_awaited()

    def test_natural_routine_aliases_include_gmail_calendar_and_drive(self):
        gmail=platform_router._EVENT_ALIASES['gmail message'];calendar=platform_router._EVENT_ALIASES['google calendar event'];drive=platform_router._EVENT_ALIASES['google drive file changes']
        self.assertEqual(gmail,'email.received');self.assertEqual(calendar,'calendar.event.started');self.assertEqual(drive,'drive.file.changed')


if __name__=='__main__':unittest.main()
