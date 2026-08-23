import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import agent_chat_presence, team_orchestrator


class GroupChatLiveFeedbackRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.temp.name)
        self.workspace_patch = patch.object(team_orchestrator, "WORKSPACE", root)
        self.file_patch = patch.object(team_orchestrator, "TEAM_FILE", root / "team_jobs.json")
        self.workspace_patch.start()
        self.file_patch.start()

    def tearDown(self):
        self.file_patch.stop()
        self.workspace_patch.stop()
        self.temp.cleanup()

    @staticmethod
    def _job(job_id, mode, status="completed", handoffs=None):
        return {
            "id": job_id,
            "task": "what's up" if mode == "chat" else "prepare the report",
            "status": status,
            "interaction_mode": mode,
            "agent_ids": ["a1", "a2"],
            "agent_names": ["CEO", "Vera"],
            "handoffs": handoffs or [],
            "completion_notified_at": None,
            "created_at": "2026-08-23T00:00:00+01:00",
            "updated_at": "2026-08-23T00:00:00+01:00",
            "final_output": None,
        }

    def test_casual_chat_completion_never_emits_collaboration_card(self):
        chat = self._job("team_chat", "chat")
        task = self._job("team_task", "task")
        team_orchestrator._save([chat, task])

        events = team_orchestrator.poll_team_completion_events()

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["card"]["id"], "team_task")
        self.assertEqual(events[0]["card"]["interaction_mode"], "task")
        self.assertIn("Agent collaboration completed", events[0]["message"])
        stored_chat = team_orchestrator.get_team_job("team_chat")
        self.assertIsNotNone(stored_chat["completion_notified_at"])

    def test_hidden_chat_job_drives_real_group_presence(self):
        handoffs = [
            {"id": "h1", "to_agent_id": "a1", "to_agent_name": "CEO", "status": "working"},
            {"id": "h2", "to_agent_id": "a2", "to_agent_name": "Vera", "status": "queued"},
        ]
        team_orchestrator._save([self._job("team_chat", "chat", status="working", handoffs=handoffs)])
        card = {
            "participant_ids": ["a1", "a2"],
            "participants": ["CEO", "Vera"],
            "messages": [
                {
                    "id": "m1",
                    "sender_type": "user",
                    "sender_id": None,
                    "at": "2026-08-23T00:00:01+01:00",
                    "metadata": {"team_job_id": "team_chat", "interaction_mode": "chat"},
                }
            ],
        }

        presence = agent_chat_presence._presence(card)
        by_id = {row["agent_id"]: row for row in presence}

        self.assertEqual(by_id["a1"]["status"], "working")
        self.assertEqual(by_id["a2"]["status"], "queued")
        self.assertEqual(by_id["a1"]["outstanding_tasks"], 1)
        self.assertEqual(by_id["a2"]["outstanding_tasks"], 1)

    def test_frontend_renders_real_busy_presence_as_animated_replying_state(self):
        source = Path("frontend/navigation_connect.js").read_text(encoding="utf-8")
        for marker in (
            "agentie-connected-group-typing",
            "agentie-connected-group-typing-dots",
            "@keyframes agentie-group-dot",
            "function busyPresence(d)",
            "function renderTyping(d,box)",
            "p.status==='working'||p.status==='queued'",
            "renderTyping(d,box)",
            "(d.presence||[]).map(p=>",
            "state.poll=setInterval(refreshGroup,1200)",
        ):
            self.assertIn(marker, source)

    def test_completion_poller_explicitly_separates_chat_from_task_mode(self):
        source = Path("agentie/core/team_orchestrator.py").read_text(encoding="utf-8")
        self.assertIn('str(j.get("interaction_mode") or "task").casefold()=="chat"', source)
        self.assertIn('j["completion_notified_at"]=now;changed=True;continue', source)


if __name__ == "__main__":
    unittest.main()
