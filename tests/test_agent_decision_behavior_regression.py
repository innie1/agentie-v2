import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import agent_prompt, agent_registry, manager_autopilot
from agentie.core.npc_brain import try_npc_response


class AgentDecisionBehaviorRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.agent_patch = patch.object(agent_registry, "AGENTS_FILE", root / "agents.json")
        self.prompt_patch = patch.object(agent_prompt, "PROMPTS_FILE", root / "agent_instruction_profiles.json")
        self.agent_patch.start()
        self.prompt_patch.start()
        self.ceo = agent_registry.create_agent("CEO", "Chief of Staff", "manager", purpose="Grow the company and coordinate the team")["agent"]
        self.mira = agent_registry.create_agent("Mira", "critic", "research", purpose="Challenge weak assumptions and research risks")["agent"]
        self.ben = agent_registry.create_agent("Ben", "Sales & Outreach", "general", purpose="Increase qualified sales")["agent"]

    def tearDown(self):
        self.prompt_patch.stop()
        self.agent_patch.stop()
        self.temp.cleanup()

    def test_generated_employee_prompt_has_explicit_judgment_contract(self):
        text = agent_prompt.build_agent_instructions(self.ceo)
        self.assertIn("FACTS", text)
        self.assertIn("OPINIONS", text)
        self.assertIn("RECOMMENDATIONS", text)
        self.assertIn("RISKS/UNCERTAINTY", text)
        self.assertIn("A recommendation is not authorization", text)
        self.assertIn("expected goal impact", text)
        self.assertIn("missing capabilities", text)

    def test_opinion_question_is_enriched_by_npc_instead_of_answered_as_fake_local_fact(self):
        result = try_npc_response(self.ceo, "What do you think about expanding the laundry business to offices first?")
        self.assertIsNotNone(result)
        self.assertEqual(result.get("routed_by"), "npc_context")
        self.assertIsNone(result.get("message"))
        prompt = result.get("escalate_message", "")
        self.assertIn("advice/judgment request", prompt)
        self.assertIn("FACTS", prompt)
        self.assertIn("OPINION", prompt)
        self.assertIn("RECOMMENDATION", prompt)
        self.assertIn("RISKS/UNCERTAINTY", prompt)
        self.assertIn("Chief of Staff", prompt)

    def test_manager_judgment_sees_existing_team_and_avoids_duplicate_specialists(self):
        result = try_npc_response(self.ceo, "Which should we prioritize first, more sales outreach or more market research?")
        prompt = result.get("escalate_message", "")
        self.assertIn("Existing Agentie team", prompt)
        self.assertIn("Mira (critic)", prompt)
        self.assertIn("Ben (Sales & Outreach)", prompt)
        self.assertIn("do not recommend a duplicate specialist", prompt)
        self.assertIn("urgency", prompt)
        self.assertIn("reversibility", prompt)

    def test_consequential_advice_does_not_turn_into_execution(self):
        result = try_npc_response(self.ceo, "Should we spend 200000 on ads this week?")
        prompt = result.get("escalate_message", "")
        self.assertIn("potentially consequential action", prompt)
        self.assertIn("do not execute it", prompt)
        self.assertIn("permission/approval gate", prompt)

    def test_simple_acknowledgement_remains_provider_free_npc_response(self):
        result = try_npc_response(self.ceo, "ok")
        self.assertEqual(result.get("routed_by"), "npc_brain")
        self.assertEqual(result.get("message"), "Okay.")
        self.assertNotIn("escalate_message", result)

    def test_pure_manager_advice_does_not_start_autopilot(self):
        self.assertIsNone(manager_autopilot.build_autopilot_plan(
            "Should we spend more on advertising or focus on sales outreach first?", self.ceo
        ))
        self.assertIsNone(manager_autopilot.build_autopilot_plan(
            "Should we research the market, build an app, and verify it before launch?", self.ceo
        ))

    def test_explicit_multistage_execution_still_uses_manager_autopilot(self):
        plan = manager_autopilot.build_autopilot_plan(
            "Research the market, build the app, then verify it is ready to launch.", self.ceo
        )
        self.assertIsNotNone(plan)
        self.assertGreaterEqual(len(plan["steps"]), 2)

    def test_global_assistant_contract_preserves_approval_and_judgment_rules(self):
        text = Path("agentie/agents/assistant.py").read_text(encoding="utf-8")
        self.assertIn("Advice is not authorization", text)
        self.assertIn("distinguish supported facts from opinions, recommendations, and risks/uncertainty", text)
        self.assertIn("do not turn ordinary advice or conversation into a background job unnecessarily", text)


if __name__ == "__main__":
    unittest.main()