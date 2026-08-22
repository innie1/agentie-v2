import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agentie.core import agent_registry, agent_threads, group_chat_policy, runner, team_orchestrator
from agentie.core import platform_next4_api  # installs the connected group-chat policy


class GroupChatQualityPolicyRegressionTests(unittest.TestCase):
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
        self.thread = agent_threads.create_thread("brain storm", [self.ceo["id"], self.mira["id"]])

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_group_task_is_marked_concise_before_worker_starts(self):
        with patch.object(agent_threads, "start_team_job"):
            row = agent_threads.post_message(
                self.thread["id"],
                "user",
                None,
                "User",
                "@CEO @Mira compare opening a laundry business vs a gaming shop and each give your view",
            )
        job = team_orchestrator.get_team_job(row["metadata"]["team_job_id"])
        self.assertEqual(job["surface"], "group_chat")
        self.assertEqual(job["response_detail"], "concise")
        self.assertEqual(job["interaction_mode"], "task")
        self.assertEqual(job["handoffs"][0]["context"], {"task": job["task"]})

    def test_explicit_detailed_request_keeps_detail_available(self):
        with patch.object(agent_threads, "start_team_job"):
            row = agent_threads.post_message(
                self.thread["id"],
                "user",
                None,
                "User",
                "@CEO @Mira give me a detailed comparison and full report on both options",
            )
        job = team_orchestrator.get_team_job(row["metadata"]["team_job_id"])
        self.assertEqual(job["surface"], "group_chat")
        self.assertEqual(job["response_detail"], "detailed")

    def test_runtime_prompt_requires_role_specific_view_and_evidence_discipline(self):
        with patch.object(agent_threads, "start_team_job"):
            row = agent_threads.post_message(
                self.thread["id"], "user", None, "User", "@Mira compare option A and B and give your view"
            )
        job_id = row["metadata"]["team_job_id"]
        huge = (
            "My view: option A is safer because it has steadier demand. " * 25
            + "\n\n## Executive Handoff Summary\nInternal status that must not appear."
        )
        original = AsyncMock(return_value=huge)
        with patch.object(group_chat_policy, "_ORIGINAL_RUN_AGENT", new=original):
            output = asyncio.run(
                runner.run_agent(
                    "internal handoff prompt",
                    "general",
                    f"{self.mira['session_prefix']}handoff:{job_id}",
                )
            )
        prompt = original.await_args.args[0]
        self.assertIn("Give YOUR role-specific view", prompt)
        self.assertIn("Do not synthesize a full-team report", prompt)
        self.assertIn("do not call a claim verified/factual unless it was actually verified", prompt)
        self.assertIn("label it as an estimate", prompt)
        self.assertLessEqual(len(output), 851)
        self.assertNotIn("Executive Handoff Summary", output)
        self.assertNotIn("Internal status", output)

    def test_internal_handoff_heading_variants_are_removed_from_visible_chat(self):
        raw = "Useful answer here.\n\n### Executive Handoff Summary\n**Next Steps:** internal only"
        cleaned = group_chat_policy.clean_group_output(raw)
        self.assertEqual(cleaned, "Useful answer here.")
        visible = agent_threads._visible_agent_reply(raw, "task")
        self.assertEqual(visible, "Useful answer here.")

    def test_markdown_renderer_is_safe_and_bundled(self):
        script = Path("frontend/group_chat_markdown.js").read_text(encoding="utf-8")
        self.assertIn("__agentieGroupChatMarkdown", script)
        self.assertIn("replace(/[&<>\"']/g", script)
        self.assertIn("<table>", script)
        self.assertIn("data-md-rendered", script)
        paths = [getattr(r, "path", None) for r in platform_next4_api.router.routes]
        self.assertIn("/platform-group-chat-markdown.js", paths)
        route = next(r for r in platform_next4_api.router.routes if getattr(r, "path", None) == "/platform-next4.js")
        body = asyncio.run(route.endpoint()).body.decode("utf-8")
        self.assertIn("__agentieGroupChatMarkdown", body)


if __name__ == "__main__":
    unittest.main()
