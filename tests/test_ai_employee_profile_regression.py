import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from agentie.core import agent_prompt, agent_registry, role_store


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

    def test_employee_identity_fields_are_persistent_and_local(self):
        agent = agent_registry.create_agent("Ben", "Sales & Outreach", "general")["agent"]
        self.assertEqual(agent["avatar_kind"], "default")
        self.assertEqual(agent["personality"], "")
        self.assertEqual(agent["goal"], "")
        self.assertEqual(agent["responsibilities"], [])
        self.assertEqual(agent["company_identity"], "")

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
        self.assertIn("make recommendations, flag risks, and respectfully disagree", prompt)
        self.assertIn("facts from recommendations/opinions", prompt)

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


if __name__ == "__main__":
    unittest.main()
