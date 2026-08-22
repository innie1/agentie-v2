import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import agent_registry,agent_threads,team_orchestrator


class GroupChatLegacyCleanupRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);root=Path(self.temp.name)
        self.patches=[
            patch.object(agent_registry,'WORKSPACE',root),patch.object(agent_registry,'AGENTS_FILE',root/'agents.json'),
            patch.object(agent_threads,'WORKSPACE',root),patch.object(agent_threads,'THREADS',root/'agent_threads.json'),
            patch.object(team_orchestrator,'WORKSPACE',root),patch.object(team_orchestrator,'TEAM_FILE',root/'team_jobs.json'),
        ]
        for p in self.patches:p.start()
        self.agent=agent_registry.create_agent('Mira','critic')['agent']
        self.thread=agent_threads.create_thread('brain storm',[self.agent['id']])

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def test_old_job_without_interaction_mode_is_inferred_and_cleaned_on_render(self):
        job=team_orchestrator.create_team_job('hi',[self.agent])
        def make_legacy(j):
            j.pop('interaction_mode',None);j['status']='completed';j['final_output']='Mira: huge internal output'
            h=j['handoffs'][0];h['context'].pop('interaction_mode',None);h.update(status='completed',result='### Deliverable\nHey! Good to see you.\n\n### Handoff Summary\n**Current Status:** operational.',finished_at='2026-01-01T00:00:00+00:00')
        team_orchestrator._mutate(job['id'],make_legacy)
        origin=agent_threads.post_message(self.thread['id'],'user',None,'User','@Mira hi',{'team_job_id':job['id'],'mentions':['Mira'],'materialize_replies':True})
        card=agent_threads.thread_card(agent_threads.get_thread(self.thread['id']))
        user=next(x for x in card['messages'] if x['id']==origin['id'])
        reply=next(x for x in card['messages'] if (x.get('metadata') or {}).get('source')=='team_job')
        self.assertNotIn('job',user)
        self.assertEqual(reply['message'],'Hey! Good to see you.')
        self.assertNotIn('job',reply)


if __name__=='__main__':unittest.main()
