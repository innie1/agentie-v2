import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agentie.core import agent_registry, agent_threads, group_chat_policy, runner, team_orchestrator
from agentie.core import platform_next4_api  # installs the connected group-chat policy


class GroupChatLocalSmalltalkRegressionTests(unittest.TestCase):
    def test_raw_hi_uses_local_npc_response_before_any_model_prompt(self):
        agent={"id":"agent_mira","name":"Mira","role":"critic","permissions":{},"skills":[]}
        with patch.object(group_chat_policy.runner,'try_npc_response',return_value={"message":"Hi from local.","confidence":.99}) as npc:
            out=group_chat_policy.local_group_chat_response(agent,'hi',context_id='group_chat:test:mira')
        self.assertEqual(out,'Hi from local.')
        npc.assert_called_once_with(agent,'hi',session_id='group_chat:test:mira')

    def test_whats_up_has_deterministic_local_reply_without_provider(self):
        agent={"id":"agent_vera","name":"Vera","role":"verifier","permissions":{},"skills":[]}
        with patch.object(group_chat_policy.runner,'try_npc_response',side_effect=AssertionError('NPC table should not be needed for this built-in phrase')):
            out=group_chat_policy.local_group_chat_response(agent,"what's up",context_id='group_chat:test:vera')
        self.assertEqual(out,'Vera here. What are we working on?')

    def test_real_group_hi_job_never_calls_original_model_runner(self):
        temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root=Path(temp.name)
        patches=[
            patch.object(agent_registry,'WORKSPACE',root),
            patch.object(agent_registry,'AGENTS_FILE',root/'agents.json'),
            patch.object(agent_threads,'WORKSPACE',root),
            patch.object(agent_threads,'THREADS',root/'agent_threads.json'),
            patch.object(team_orchestrator,'WORKSPACE',root),
            patch.object(team_orchestrator,'TEAM_FILE',root/'team_jobs.json'),
        ]
        for item in patches:item.start()
        try:
            mira=agent_registry.create_agent('Mira','critic')['agent']
            thread=agent_threads.create_thread('brain storm',[mira['id']])
            with patch.object(agent_threads,'start_team_job'):
                row=agent_threads.post_message(thread['id'],'user',None,'User','@Mira hi')
            job_id=row['metadata']['team_job_id']
            model=AsyncMock(side_effect=AssertionError('casual hi must not call the model'))
            with patch.object(group_chat_policy,'_ORIGINAL_RUN_AGENT',new=model):
                output=asyncio.run(runner.run_agent('generated internal handoff prompt','general',f"{mira['session_prefix']}handoff:{job_id}"))
            self.assertTrue(output)
            self.assertIn('Hi',output)
            model.assert_not_awaited()
        finally:
            for item in reversed(patches):item.stop()
            temp.cleanup()

    def test_group_policy_checks_local_chat_path_before_original_runner(self):
        src=Path('agentie/core/group_chat_policy.py').read_text(encoding='utf-8')
        chat_at=src.index('if chat:\n            local = local_group_chat_response')
        return_at=src.index('return local',chat_at)
        prompt_at=src.index('prompt = _group_prompt',chat_at)
        provider_at=src.index('output = await _ORIGINAL_RUN_AGENT',prompt_at)
        self.assertLess(chat_at,return_at)
        self.assertLess(return_at,prompt_at)
        self.assertLess(prompt_at,provider_at)
        self.assertIn('"provider_calls": 0',src)

    def test_real_group_questions_still_have_model_escalation_path(self):
        agent={"id":"agent_ceo","name":"CEO","role":"coordinator","permissions":{},"skills":[]}
        with patch.object(group_chat_policy.runner,'try_npc_response',return_value=None):
            out=group_chat_policy.local_group_chat_response(agent,'compare two business models',context_id='group_chat:test:ceo')
        self.assertIsNone(out)


if __name__ == '__main__':
    unittest.main()
