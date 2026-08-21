import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from agentie.core import deep_research


class BackgroundEventOwnershipRegressionTests(unittest.TestCase):
    def test_deep_research_synthesis_bypasses_persistent_agent_session(self):
        sources=[deep_research.Source('S1','Church app','https://example.com','Evidence','Full evidence','q1')]
        async def fake_collect(*args,**kwargs):
            return ['q1'],sources,[]
        runner=AsyncMock(return_value='A sourced research report [S1].')
        with patch.object(deep_research,'collect_sources',new=fake_collect):
            result=asyncio.run(deep_research.run_deep_research('church apps',runner,'agent:agt_alex:main'))
        self.assertIn('A sourced research report',result['report'])
        args=runner.await_args.args
        self.assertEqual(args[1],'research')
        self.assertIsNone(args[2], 'Internal synthesis must not use the persistent agent chat session/NPC layer.')

    def test_frontend_persists_job_owner_and_defers_foreign_completion(self):
        raw=open('frontend/project_workspace.js',encoding='utf-8').read()
        self.assertIn("agentie.background.jobOwners.v1",raw)
        self.assertIn("agentie.background.pendingEvents.v1",raw)
        self.assertIn("rememberOwner(id,active)",raw)
        self.assertIn("active?.id!==owner.id",raw)
        self.assertIn("queue(owner.id,message,card)",raw)
        self.assertIn("previous(item.message||'',item.card||null)",raw)

    def test_artifact_creator_routes_file_to_owning_agent(self):
        raw=open('frontend/project_workspace.js',encoding='utf-8').read()
        self.assertIn("function artifactOwner(card)",raw)
        self.assertIn("card?.creator",raw)
        self.assertIn("const owner=jobOwner||fileOwner",raw)
        self.assertIn("created a file",raw)


if __name__=='__main__':
    unittest.main()
