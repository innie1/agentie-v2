import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import agent_registry, agent_threads, platform_next4_api, team_orchestrator


class GroupChatDefaultReplyRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.temp.name)
        self.patches = [
            patch.object(agent_registry, "WORKSPACE", root),
            patch.object(agent_registry, "AGENTS_FILE", root / "agents.json"),
            patch.object(agent_threads, "WORKSPACE", root),
            patch.object(agent_threads, "THREADS", root / "agent_threads.json"),
            patch.object(team_orchestrator, "WORKSPACE", root),
            patch.object(team_orchestrator, "TEAM_FILE", root / "team_jobs.json"),
        ]
        for item in self.patches:
            item.start()
        self.ceo = agent_registry.create_agent("CEO", "company coordinator")["agent"]
        self.mira = agent_registry.create_agent("Mira", "critic")["agent"]
        self.vera = agent_registry.create_agent("Vera", "verifier")["agent"]
        self.thread = agent_threads.create_thread(
            "Launch Project",
            [self.ceo["id"], self.mira["id"], self.vera["id"]],
        )

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_plain_group_message_targets_every_participant(self):
        with patch.object(agent_threads, "start_team_job") as start:
            metadata = platform_next4_api._default_group_job_metadata(self.thread, "hello everyone")
        self.assertIsNotNone(metadata)
        self.assertEqual(
            metadata["to_agent_ids"],
            [self.ceo["id"], self.mira["id"], self.vera["id"]],
        )
        self.assertEqual(metadata["mentions"], ["CEO", "Mira", "Vera"])
        self.assertTrue(metadata["materialize_replies"])
        self.assertEqual(metadata["interaction_mode"], "chat")
        self.assertEqual(metadata["source"], "group_chat_default_all")
        start.assert_called_once_with(metadata["team_job_id"])
        job = team_orchestrator.get_team_job(metadata["team_job_id"])
        self.assertEqual([x["to_agent_id"] for x in job["handoffs"]], metadata["to_agent_ids"])

    def test_explicit_mentions_keep_targeted_behavior(self):
        with patch.object(agent_threads, "start_team_job") as start:
            metadata = platform_next4_api._default_group_job_metadata(self.thread, "@Mira what do you think?")
        self.assertIsNone(metadata)
        start.assert_not_called()

    def test_message_route_passes_default_group_metadata_to_thread_store(self):
        source = Path("agentie/core/platform_next4_api.py").read_text(encoding="utf-8")
        self.assertIn("metadata = _default_group_job_metadata(thread, message)", source)
        self.assertIn('agent_threads.post_message(thread["id"], "user", None, "User", message, metadata)', source)


if __name__ == "__main__":
    unittest.main()
