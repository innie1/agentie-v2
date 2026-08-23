import unittest
from unittest.mock import patch

from agentie.core.npc_brain import role_profile, try_npc_response


class RoleNPCRegressionTests(unittest.TestCase):
    def setUp(self):
        self.cto={"id":"agt_cto","name":"Alex","role":"CTO","base":"general","purpose":"Lead engineering","skills":["code-execution"],"permissions":{"capability_mode":"shared"}}
        self.writer={"id":"agt_writer","name":"Writer","role":"Content Writer","base":"general","purpose":"Create content","skills":[],"permissions":{"capability_mode":"shared"}}
        self.researcher={"id":"agt_research","name":"Researcher","role":"Researcher","base":"general","purpose":"Research markets","skills":["research"],"permissions":{"capability_mode":"shared"}}
        self.ceo={"id":"agt_ceo","name":"CEO","role":"CEO","base":"general","purpose":"Lead company","skills":[],"permissions":{"capability_mode":"shared","delegate":True}}

    def _npc(self,agent,message):
        with patch("agentie.core.npc_brain.learn_from_user_message",return_value=[]):
            return try_npc_response(agent,message)

    def test_local_profiles_follow_configured_work_not_shared_tool_availability(self):
        self.assertEqual(role_profile(self.cto),"coding")
        self.assertEqual(role_profile(self.researcher),"research")
        self.assertEqual(role_profile(self.ceo),"planning")
        self.assertEqual(role_profile(self.writer),"general")
        same_work_without_skill={**self.cto,"skills":[]}
        self.assertEqual(role_profile(same_work_without_skill),"coding")
        title_only={**self.cto,"id":"agt_title_only","purpose":"","goal":"","responsibilities":[],"skills":[]}
        self.assertEqual(role_profile(title_only),"general")

    def test_engineering_work_handles_engineering_checklist_locally(self):
        result=self._npc(self.cto,"Give me a debug checklist")
        self.assertEqual(result["routed_by"],"npc_brain");self.assertEqual(result["npc_role"],"coding")
        self.assertIn("regression",result["message"].lower())

    def test_research_work_handles_research_checklist_locally(self):
        result=self._npc(self.researcher,"How should we research this?")
        self.assertEqual(result["npc_role"],"research");self.assertIn("sources",result["message"].lower())

    def test_title_without_matching_work_does_not_create_hidden_local_class(self):
        result=self._npc(self.writer,"Give me a content checklist")
        self.assertIsNone(result)

    def test_explicit_delegate_permission_handles_planning_checklist_locally(self):
        result=self._npc(self.ceo,"How should we plan this?")
        self.assertEqual(result["npc_role"],"planning");self.assertIn("milestones",result["message"].lower())

    def test_complex_configured_work_still_falls_back_to_provider(self):
        result=self._npc(self.cto,"Design and implement a complete distributed event driven architecture for my production system with code")
        self.assertIsNone(result)

    def test_role_identity_question_uses_configured_job_without_hidden_profile(self):
        result=self._npc(self.writer,"What is your role?")
        self.assertEqual(result["routed_by"],"npc_brain");self.assertIn("Content Writer",result["message"])
        self.assertEqual(result["npc_role"],"general")


if __name__=="__main__":unittest.main()
