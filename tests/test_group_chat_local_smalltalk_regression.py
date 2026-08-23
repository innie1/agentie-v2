import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import group_chat_policy


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
