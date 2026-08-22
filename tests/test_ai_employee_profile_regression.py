import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from agentie.core import agent_prompt, agent_registry, role_store
from agentie.core.npc_brain import try_npc_response


class AIEmployeeProfileRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [
            patch.object(agent_registry, "WORKSPACE", self.root),
            patch.object(agent_registry, "AGENTS_FILE", self.root / "agents.json"),
            patch.object(role_store, "WORKSPACE", self.root),
            patch.object(role_store, "ROLES", self.root / "agent_roles.json"),
            patch.object(agent_prompt, "WORKSPACE", self.root),
            patch.object(agent_prompt, "PROMPTS_FILE", self.root / "agent_instruction_profiles.json"),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_employee_identity_fields_are_generated_persistent_and_user_editable(self):
        agent = agent_registry.create_agent("Ben", "Sales & Outreach", "general")["agent"]
        self.assertEqual(agent["avatar_kind"], "default")
        self.assertTrue(agent["personality"])
        self.assertTrue(agent["goal"])
        self.assertGreaterEqual(len(agent["responsibilities"]), 3)
        self.assertEqual(agent["company_identity"], "")
        self.assertIn("sales", agent["goal"].lower())

        role_store.route_role_command(f"Set agent {agent['id']} personality to Friendly, professional, proactive")
        role_store.route_role_command(f"Set agent {agent['id']} goal to Increase sales")
        role_store.route_role_command(f"Set agent {agent['id']} responsibilities to Follow up leads | Review pipeline | Recommend next actions")
        result = role_store.route_role_command(f"Set agent {agent['id']} company identity to COAN Industries")

        updated = agent_registry.get_agent(agent["id"])
        self.assertEqual(updated["personality"], "Friendly, professional, proactive")
        self.assertEqual(updated["goal"], "Increase sales")
        self.assertEqual(updated["responsibilities"], ["Follow up leads", "Review pipeline", "Recommend next actions"])
        self.assertEqual(updated["company_identity"], "COAN Industries")
        self.assertEqual(result["card"]["type"], "agent_profile")

    def test_creation_does_not_turn_job_titles_or_legacy_base_into_hidden_agent_types(self):
        coordinator_title = agent_registry.create_agent("Gemma", "Chief of Staff", "manager")["agent"]
        self.assertEqual(coordinator_title["base"], "general")
        self.assertEqual(coordinator_title["runtime_profile"], "general")
        self.assertFalse(bool(coordinator_title["permissions"].get("delegate")))
        self.assertIn("chief of staff", coordinator_title["goal"].lower())
        self.assertEqual(coordinator_title["company_identity"], "")

        researcher_title = agent_registry.create_agent(
            "Mira",
            "Market Research Analyst",
            "research",
            purpose="Study laundry demand in Warri",
        )["agent"]
        self.assertEqual(researcher_title["base"], "general")
        self.assertEqual(researcher_title["runtime_profile"], "general")
        self.assertIn("research", researcher_title["goal"].lower())
        self.assertIn("laundry demand in Warri", researcher_title["goal"])
        self.assertEqual(researcher_title["company_identity"], "")

        explicit = agent_registry.create_agent(
            "Nora",
            "Operations Coordinator",
            permissions={"delegate": True, "shared_company_memory": "read"},
        )["agent"]
        self.assertTrue(explicit["permissions"]["delegate"])

    def test_npc_explicit_statements_update_the_same_persistent_profile(self):
        agent = agent_registry.create_agent("Ben", "Sales & Outreach", "general")["agent"]
        response = try_npc_response(agent, "Your goal is Grow recurring sales in Nigeria")
        self.assertEqual(response["routed_by"], "npc_brain")
        self.assertTrue(any("employee profile goal" in x.lower() for x in response["learned"]))
        updated = agent_registry.get_agent(agent["id"])
        self.assertEqual(updated["goal"], "Grow recurring sales in Nigeria")

        response = try_npc_response(updated, "Your responsibilities are Follow up leads | Review pipeline | Recommend next actions")
        self.assertEqual(response["routed_by"], "npc_brain")
        updated = agent_registry.get_agent(agent["id"])
        self.assertEqual(updated["responsibilities"], ["Follow up leads", "Review pipeline", "Recommend next actions"])

        response = try_npc_response(updated, "You work for COAN Industries")
        self.assertEqual(response["routed_by"], "npc_brain")
        updated = agent_registry.get_agent(agent["id"])
        self.assertEqual(updated["company_identity"], "COAN Industries")

    def test_identity_is_used_by_generated_agent_prompt(self):
        agent = agent_registry.create_agent("Ben", "Sales & Outreach", "general")["agent"]
        updated = agent_registry.update_agent_profile(
            agent["id"],
            personality="Friendly, professional, proactive",
            goal="Increase sales",
            responsibilities=["Follow up leads", "Review pipeline"],
            company_identity="COAN Industries",
        )
        prompt = agent_prompt.build_agent_instructions(updated)
        self.assertIn("You are Ben, a persistent Agentie AI employee.", prompt)
        self.assertIn("Company identity: COAN Industries", prompt)
        self.assertIn("Personality and working style: Friendly, professional, proactive.", prompt)
        self.assertIn("Primary goal: Increase sales.", prompt)
        self.assertIn("Follow up leads", prompt)
        self.assertIn("make a recommendation, flag meaningful risks, and respectfully disagree", prompt)
        self.assertIn("FACTS are supported by known context or verified evidence", prompt)
        self.assertIn("OPINIONS are your role-based judgment", prompt)
        self.assertIn("RECOMMENDATIONS are the action or option you advise", prompt)
        self.assertIn("RISKS/UNCERTAINTY", prompt)

    def test_generated_and_uploaded_avatars_are_real_persistent_modes(self):
        agent = agent_registry.create_agent("Ben", "Sales", "general")["agent"]
        generated = agent_registry.set_agent_avatar(agent["id"], "generated")
        self.assertEqual(generated["avatar_kind"], "generated")
        self.assertIsNone(generated["avatar_file"])

        uploads = self.root / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        filename = f"agent-avatar-{agent['id']}-test.png"
        path = uploads / filename
        Image.new("RGB", (32, 32), (20, 30, 40)).save(path)
        uploaded = agent_registry.set_agent_avatar(agent["id"], "uploaded", filename)
        self.assertEqual(uploaded["avatar_kind"], "uploaded")
        self.assertEqual(uploaded["avatar_file"], filename)
        self.assertTrue(path.exists())

        reset = agent_registry.set_agent_avatar(agent["id"], "default")
        self.assertEqual(reset["avatar_kind"], "default")
        self.assertIsNone(reset["avatar_file"])
        self.assertFalse(path.exists())

    def test_avatar_rejects_unowned_or_non_image_uploads(self):
        agent = agent_registry.create_agent("Ben", "Sales", "general")["agent"]
        uploads = self.root / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        wrong = uploads / "random.txt"
        wrong.write_text("not an avatar", encoding="utf-8")
        with self.assertRaises(ValueError):
            agent_registry.set_agent_avatar(agent["id"], "uploaded", wrong.name)

    def test_profile_ui_uses_existing_top_chat_avatar_and_real_agent_data(self):
        text = Path("frontend/plugins.js").read_text(encoding="utf-8")
        profile = text.split("// AI employee identity/profile v2.", 1)[1]
        self.assertIn("no second agent store", profile)
        self.assertIn(".top-agent-orb", profile)
        self.assertIn("openProfile(activeAgent())", profile)
        self.assertIn("Open ${a.name} profile", profile)
        self.assertIn("employee-profile-stats", profile)
        self.assertIn("stat('Skills'", profile)
        self.assertIn("stat('Duties'", profile)
        self.assertIn("stat('Permissions'", profile)
        self.assertIn("Generate local avatar", profile)
        self.assertIn("/files/upload", profile)
        self.assertNotIn("72.9K", profile)
        self.assertNotIn("342.9K", profile)
        self.assertNotIn("Likes", profile)
        self.assertNotIn("Views", profile)

    def test_profile_instructions_toggle_reuses_the_same_modal_and_profile_card(self):
        text = Path("frontend/project_workspace.js").read_text(encoding="utf-8")
        self.assertIn("__agentieProfileInstructionsToggle", text)
        self.assertIn("const profileCard=modal.querySelector('.employee-profile-card')", text)
        self.assertIn("profileCard.remove()", text)
        self.assertIn("modal.appendChild(profileCard)", text)
        self.assertIn("Generated system instructions", text)
        self.assertIn("Save instructions", text)
        self.assertIn("Set agent ${agent.id} instructions to ${manual}", text)
        self.assertIn("e.stopImmediatePropagation()", text)

    def test_top_avatar_refreshes_profile_before_opening_it(self):
        text = Path("frontend/project_workspace.js").read_text(encoding="utf-8")
        self.assertIn("Show agent ${agent.id}", text)
        self.assertIn("openFreshProfile(agent)", text)
        self.assertIn("window.openAgentProfile(fresh)", text)


if __name__ == "__main__":
    unittest.main()
