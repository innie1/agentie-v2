import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agentie.core import telegram_channel
from agentie.tools import approval_tools


class TelegramChannelRegressionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        self.old=(telegram_channel.STATE_FILE,telegram_channel.KEY_FILE,approval_tools.STORE)
        telegram_channel.STATE_FILE=root/"telegram.json";telegram_channel.KEY_FILE=root/"telegram.key";approval_tools.STORE=root/"approvals.json"
        telegram_channel._TASKS.clear();telegram_channel._HANDLER=None

    def tearDown(self):
        for task in telegram_channel._TASKS.values():task.cancel()
        telegram_channel._TASKS.clear();telegram_channel.STATE_FILE,telegram_channel.KEY_FILE,approval_tools.STORE=self.old;self.tmp.cleanup()

    async def _configured(self,owner="tenant-a"):
        token="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd1234"
        async def fake_api(_token,method,payload=None,attempts=4):
            if method=="getMe":return {"id":901,"username":"agentie_test_bot"}
            return True
        with patch.object(telegram_channel,"api_request",side_effect=fake_api),patch.object(telegram_channel,"start_owner",new=AsyncMock()):
            await telegram_channel.configure(owner,token)
        return token

    async def test_tokens_are_encrypted_and_tenants_are_isolated(self):
        token=await self._configured("tenant-a");await self._configured("tenant-b")
        raw=telegram_channel.STATE_FILE.read_text(encoding="utf-8")
        self.assertNotIn(token,raw);self.assertNotIn(token,json.dumps(telegram_channel.public_state("tenant-a")))
        data=telegram_channel._load();data["tenant-a"]["paired_chat_id"]=11;data["tenant-b"]["paired_chat_id"]=22;telegram_channel._save(data)
        self.assertEqual(telegram_channel.public_state("tenant-a")["paired_chat_id"],"11")
        self.assertEqual(telegram_channel.public_state("tenant-b")["paired_chat_id"],"22")

    async def test_pairing_is_one_time_private_and_unauthorized_messages_are_ignored(self):
        token=await self._configured();state=telegram_channel.create_pair_code("tenant-a")
        sent=[]
        async def fake_api(_token,method,payload=None,attempts=4):sent.append((method,payload));return True
        group={"update_id":1,"message":{"text":state["pair_code"],"chat":{"id":8,"type":"group"},"from":{"id":7}}}
        with patch.object(telegram_channel,"api_request",side_effect=fake_api):await telegram_channel.process_update("tenant-a",group,token)
        self.assertFalse(telegram_channel.public_state("tenant-a")["connected"])
        private={"update_id":2,"message":{"text":state["pair_code"],"chat":{"id":8,"type":"private"},"from":{"id":7,"username":"alice"}}}
        with patch.object(telegram_channel,"api_request",side_effect=fake_api):await telegram_channel.process_update("tenant-a",private,token)
        self.assertTrue(telegram_channel.public_state("tenant-a")["connected"])
        handler=AsyncMock(return_value={"message":"secret reply","card":None});telegram_channel.set_handler(handler)
        unauthorized={"message":{"text":"hello","chat":{"id":99,"type":"private"},"from":{"id":55}}}
        with patch.object(telegram_channel,"api_request",side_effect=fake_api):await telegram_channel.process_update("tenant-a",unauthorized,token)
        handler.assert_not_awaited()

    async def test_inbound_routes_active_agent_and_commands(self):
        token=await self._configured();data=telegram_channel._load();data["tenant-a"].update({"paired_chat_id":8,"paired_user_id":7});telegram_channel._save(data)
        handler=AsyncMock(return_value={"message":"Ben replied","card":None});telegram_channel.set_handler(handler);sent=[]
        async def fake_api(_token,method,payload=None,attempts=4):sent.append((method,payload));return True
        update={"message":{"text":"hello","chat":{"id":8,"type":"private"},"from":{"id":7}}}
        with patch.object(telegram_channel,"api_request",side_effect=fake_api):await telegram_channel.process_update("tenant-a",update,token)
        handler.assert_awaited_once_with("tenant-a","general","hello");self.assertIn("Ben replied",sent[-1][1]["text"])

    async def test_poller_persists_offset_and_skips_duplicate_updates(self):
        await self._configured();data=telegram_channel._load();data["tenant-a"].update({"paired_chat_id":8,"paired_user_id":7,"offset":5});telegram_channel._save(data)
        processed=[]
        async def fake_api(_token,method,payload=None,attempts=4):
            self.assertEqual(payload["offset"],5);return [{"update_id":4},{"update_id":5},{"update_id":6}]
        async def fake_process(owner,update,token=None):processed.append(update["update_id"])
        with patch.object(telegram_channel,"api_request",side_effect=fake_api),patch.object(telegram_channel,"process_update",side_effect=fake_process):count=await telegram_channel.poll_once("tenant-a")
        self.assertEqual(count,2);self.assertEqual(processed,[5,6]);self.assertEqual(telegram_channel._load()["tenant-a"]["offset"],7)

    async def test_approval_buttons_use_existing_approval_store(self):
        token=await self._configured();data=telegram_channel._load();data["tenant-a"].update({"paired_chat_id":8,"paired_user_id":7});telegram_channel._save(data)
        approval=approval_tools.create_approval("sports bet submit","Place a real-money wager",{"kind":"test"})
        callback={"callback_query":{"id":"cb1","data":f"approval:{approval['id']}:reject","from":{"id":7},"message":{"message_id":44,"chat":{"id":8}}}}
        async def fake_api(_token,method,payload=None,attempts=4):return True
        with patch.object(telegram_channel,"api_request",side_effect=fake_api):await telegram_channel.process_update("tenant-a",callback,token)
        self.assertEqual(approval_tools.get_approval(approval["id"])["status"],"denied")

    async def test_proactive_routine_delivery_retry_and_disconnect_revoke(self):
        token=await self._configured();data=telegram_channel._load();data["tenant-a"].update({"paired_chat_id":8,"paired_user_id":7});telegram_channel._save(data)
        self.assertEqual(telegram_channel.queue_proactive("Routine finished",{"type":"routine_run"}),1)
        calls=0
        async def limited(_token,method,payload=None,attempts=4):
            nonlocal calls;calls+=1
            if calls==1:raise telegram_channel.TelegramError("Too Many Requests",code=429,retry_after=2)
            return True
        with patch.object(telegram_channel,"api_request",side_effect=limited):self.assertEqual(await telegram_channel.flush_outbox("tenant-a"),0)
        row=telegram_channel._load()["tenant-a"];row["outbox"][0]["next_attempt"]=0;data=telegram_channel._load();data["tenant-a"]=row;telegram_channel._save(data)
        with patch.object(telegram_channel,"api_request",side_effect=limited):self.assertEqual(await telegram_channel.flush_outbox("tenant-a"),1)
        state=await telegram_channel.disconnect("tenant-a",revoke_token=True);self.assertFalse(state["configured"]);self.assertNotIn(token,telegram_channel.STATE_FILE.read_text(encoding="utf-8"))

    async def test_reports_and_images_are_uploaded_from_workspace(self):
        root=telegram_channel.WORKSPACE;root.mkdir(parents=True,exist_ok=True);report=root/"telegram-test-report.txt";report.write_text("verified report",encoding="utf-8")
        try:
            with patch.object(telegram_channel,"_upload_sync",return_value=True) as upload:
                self.assertTrue(await telegram_channel._send_attachment("token",8,{"path":str(report),"kind":"document","title":"Report"}))
            self.assertEqual(upload.call_args.args[1],"sendDocument")
        finally:report.unlink(missing_ok=True)

    def test_ui_and_api_are_real_plugin_integration(self):
        source=Path("main.py").read_text(encoding="utf-8");ui=Path("frontend/telegram_plugin.js").read_text(encoding="utf-8")
        for value in ('/plugins/telegram','/plugins/telegram/pair','start_telegram_channels','telegram-plugin.js'):self.assertIn(value,source+ui)
        self.assertIn('BotFather',ui);self.assertIn('revoke_token=true',ui)
        plugins=Path("frontend/plugins.js").read_text(encoding="utf-8");self.assertIn('plugins-mobile-launch',plugins);self.assertIn("mobileButton.onclick=togglePlugins",plugins)


if __name__=="__main__":unittest.main()
