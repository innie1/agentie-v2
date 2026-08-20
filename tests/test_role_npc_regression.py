import unittest
from unittest.mock import patch

from agentie.core.npc_brain import role_profile, try_npc_response


class RoleNPCRegressionTests(unittest.TestCase):
    def setUp(self):
        self.cto={"id":"agt_cto","name":"Alex","role":"CTO","base":"manager","purpose":"Lead engineering"}
        self.writer={"id":"agt_writer","name":"Writer","role":"Content Writer","base":"general","purpose":"Create content"}
        self.researcher={"id":"agt_research","name":"Researcher","role":"Researcher","base":"research","purpose":"Research markets"}
        self.ceo={"id":"agt_ceo","name":"CEO","role":"CEO","base":"manager","purpose":"Lead company"}

    def _npc(self,agent,message):
        with patch("agentie.core.npc_brain.learn_from_user_message",return_value=[]):
            return try_npc_response(agent,message)

    def test_roles_map_to_different_npc_profiles(self):
        self.assertEqual(role_profile(self.cto),"coding")
        self.assertEqual(role_profile(self.writer),"writing")
        self.assertEqual(role_profile(self.researcher),"research")
        self.assertEqual(role_profile(self.ceo),"planning")

    def test_cto_handles_engineering_checklist_locally(self):
        result=self._npc(self.cto,"Give me a debug checklist")
        self.assertEqual(result["routed_by"],"npc_brain");self.assertEqual(result["npc_role"],"coding")
        self.assertIn("regression",result["message"].lower())

    def test_researcher_handles_research_checklist_locally(self):
        result=self._npc(self.researcher,"How should we research this?")
        self.assertEqual(result["npc_role"],"research");self.assertIn("sources",result["message"].lower())

    def test_writer_handles_content_checklist_locally(self):
        result=self._npc(self.writer,"Give me a content checklist")
        self.assertEqual(result["npc_role"],"writing");self.assertIn("audience",result["message"].lower())

    def test_manager_handles_planning_checklist_locally(self):
        result=self._npc(self.ceo,"How should we plan this?")
        self.assertEqual(result["npc_role"],"planning");self.assertIn("milestones",result["message"].lower())

    def test_complex_role_task_still_falls_back_to_provider(self):
        result=self._npc(self.cto,"Design and implement a complete distributed event driven architecture for my production system with code")
        self.assertIsNone(result)

    def test_role_identity_question_is_local(self):
        result=self._npc(self.cto,"What is your role?")
        self.assertEqual(result["routed_by"],"npc_brain");self.assertIn("CTO",result["message"])


if __name__=="__main__":unittest.main()
