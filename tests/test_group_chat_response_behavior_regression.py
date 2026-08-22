import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch

from agentie.core import agent_registry,agent_threads,team_orchestrator


class GroupChatResponseBehaviorRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);root=Path(self.temp.name)
        self.patches=[
            patch.object(agent_registry,'WORKSPACE',root),patch.object(agent_registry,'AGENTS_FILE',root/'agents.json'),
            patch.object(agent_threads,'WORKSPACE',root),patch.object(agent_threads,'THREADS',root/'agent_threads.json'),
            patch.object(team_orchestrator,'WORKSPACE',root),patch.object(team_orchestrator,'TEAM_FILE',root/'team_jobs.json'),
        ]
        for p in self.patches:p.start()
        self.ceo=agent_registry.create_agent('CEO','company coordinator')['agent']
        self.mira=agent_registry.create_agent('Mira','critic')['agent']
        self.vera=agent_registry.create_agent('Vera','verifier')['agent']
        self.thread=agent_threads.create_thread('brain storm',[self.ceo['id'],self.mira['id'],self.vera['id']])

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def _complete_job(self,job_id,result):
        def done(job):
            for handoff in job['handoffs']:
                handoff.update(status='completed',result=result,error=None,finished_at='2026-01-01T00:00:00+00:00')
            job['status']='completed';job['final_output']='\n\n---\n\n'.join(f"{h['to_agent_name']}:\n{result}" for h in job['handoffs']);job['finished_at']='2026-01-01T00:00:00+00:00'
        team_orchestrator._mutate(job_id,done)

    def test_short_social_message_is_chat_not_formal_task(self):
        self.assertEqual(agent_threads._interaction_mode('hi'),'chat')
        self.assertEqual(agent_threads._interaction_mode("what's going on"),'chat')
        self.assertEqual(agent_threads._interaction_mode('compare these two plans and recommend one'),'task')

    def test_mentions_create_chat_mode_team_job_for_social_message(self):
        with patch.object(agent_threads,'start_team_job'):
            row=agent_threads.post_message(self.thread['id'],'user',None,'User','@CEO @Mira @Vera hi')
        job=team_orchestrator.get_team_job(row['metadata']['team_job_id'])
        self.assertEqual(job['interaction_mode'],'chat')
        self.assertTrue(all(h['context']['interaction_mode']=='chat' for h in job['handoffs']))
        self.assertEqual(row['metadata']['interaction_mode'],'chat')

    def test_chat_worker_prompt_requests_normal_reply_not_handoff_report(self):
        job=team_orchestrator.create_team_job('hi',[self.mira],interaction_mode='chat')
        handoff=job['handoffs'][0]
        run=AsyncMock(return_value='Hey! What are we working on?')
        with patch('agentie.core.runner.run_agent',new=run):
            hid,out,err=asyncio.run(team_orchestrator._worker(job['id'],handoff))
        self.assertEqual(hid,handoff['id']);self.assertIsNone(err);self.assertEqual(out,'Hey! What are we working on?')
        prompt=run.await_args.args[0]
        self.assertIn('replying directly inside an Agentie group chat',prompt)
        self.assertIn('1-3 sentences',prompt)
        self.assertIn('Do not output headings',prompt)
        self.assertNotIn('Return a useful deliverable and a concise handoff summary',prompt)

    def test_chat_card_hides_job_scaffolding_and_combined_output(self):
        with patch.object(agent_threads,'start_team_job'):
            origin=agent_threads.post_message(self.thread['id'],'user',None,'User','@CEO @Mira @Vera hi')
        raw='### Deliverable\nHello! Nice to hear from you.\n\n---\n\n### Handoff Summary\n**Current Status:** Operational.\n**Role Focus:** Internal details.'
        self._complete_job(origin['metadata']['team_job_id'],raw)
        card=agent_threads.thread_card(agent_threads.get_thread(self.thread['id']))
        user=next(x for x in card['messages'] if x['id']==origin['id'])
        self.assertNotIn('job',user)
        replies=[x for x in card['messages'] if (x.get('metadata') or {}).get('source')=='team_job']
        self.assertEqual(len(replies),3)
        for reply in replies:
            self.assertEqual(reply['message'],'Hello! Nice to hear from you.')
            self.assertNotIn('Deliverable',reply['message'])
            self.assertNotIn('Handoff Summary',reply['message'])
            self.assertNotIn('Current Status',reply['message'])
            self.assertNotIn('job',reply)

    def test_real_task_keeps_small_status_on_origin_but_not_duplicate_final_output(self):
        with patch.object(agent_threads,'start_team_job'):
            origin=agent_threads.post_message(self.thread['id'],'user',None,'User','@Mira compare option A and option B and recommend one')
        raw='### Deliverable\nOption A is safer. I recommend A.\n\n### Handoff Summary\nInternal worker status.'
        self._complete_job(origin['metadata']['team_job_id'],raw)
        card=agent_threads.thread_card(agent_threads.get_thread(self.thread['id']))
        user=next(x for x in card['messages'] if x['id']==origin['id'])
        self.assertIn('job',user)
        self.assertEqual(user['job']['interaction_mode'],'task')
        self.assertNotIn('final_output',user['job'])
        reply=next(x for x in card['messages'] if (x.get('metadata') or {}).get('source')=='team_job')
        self.assertEqual(reply['message'],'Option A is safer. I recommend A.')
        self.assertNotIn('job',reply)


if __name__=='__main__':unittest.main()
