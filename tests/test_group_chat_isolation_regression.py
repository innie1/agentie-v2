import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import agent_threads


class GroupChatIsolationRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.old_workspace = agent_threads.WORKSPACE
        self.old_threads = agent_threads.THREADS
        root = Path(self.temp.name)
        agent_threads.WORKSPACE = root
        agent_threads.THREADS = root / "agent_threads.json"
        self.agents = {
            "a": {"id": "a", "name": "Alpha"},
            "b": {"id": "b", "name": "Beta"},
            "c": {"id": "c", "name": "Gamma"},
        }
        self.agent_patch = patch.object(agent_threads, "get_agent", side_effect=lambda key: self.agents.get(str(key)))
        self.agent_patch.start()

    def tearDown(self):
        self.agent_patch.stop()
        agent_threads.WORKSPACE = self.old_workspace
        agent_threads.THREADS = self.old_threads
        self.temp.cleanup()

    def test_backend_threads_never_return_each_others_messages(self):
        first = agent_threads.create_thread("First Group", ["a", "b"])
        second = agent_threads.create_thread("Second Group", ["b", "c"])

        agent_threads.post_message(first["id"], "agent", "a", "Alpha", "FIRST-ONLY")
        agent_threads.post_message(second["id"], "agent", "c", "Gamma", "SECOND-ONLY")

        first_now = agent_threads.get_thread(first["id"])
        second_now = agent_threads.get_thread(second["id"])
        first_text = "\n".join(x.get("message", "") for x in first_now.get("messages", []))
        second_text = "\n".join(x.get("message", "") for x in second_now.get("messages", []))

        self.assertIn("FIRST-ONLY", first_text)
        self.assertNotIn("SECOND-ONLY", first_text)
        self.assertIn("SECOND-ONLY", second_text)
        self.assertNotIn("FIRST-ONLY", second_text)

    def test_frontend_has_exactly_one_group_chat_runtime_owner(self):
        model = Path("frontend/model_router.js").read_text(encoding="utf-8")
        nav = Path("frontend/navigation_connect.js").read_text(encoding="utf-8")

        self.assertNotIn("/platform/agent-chats", model)
        self.assertNotIn("activeGroup", model)
        self.assertNotIn("refreshActiveGroup", model)
        self.assertIn("/platform/agent-chats", nav)
        self.assertIn("function refreshGroup", nav)
        self.assertIn("function openGroup", nav)

    def test_group_switch_cancels_old_poll_before_new_thread_loads(self):
        nav = Path("frontend/navigation_connect.js").read_text(encoding="utf-8")
        clear_poll = "if(state.poll){clearInterval(state.poll);state.poll=null}"
        set_pending = "state.group=known"
        fetch_next = "api(`/platform/agent-chats/${encodeURIComponent(nextId)}`"
        self.assertIn(clear_poll, nav)
        self.assertIn(set_pending, nav)
        self.assertIn(fetch_next, nav)
        self.assertLess(nav.index(clear_poll, nav.index("async function openGroup")), nav.index(set_pending, nav.index("async function openGroup")))
        self.assertLess(nav.index(set_pending, nav.index("async function openGroup")), nav.index(fetch_next, nav.index("async function openGroup")))

    def test_leaving_group_restores_normal_surface_before_agent_switch_saves_view(self):
        nav = Path("frontend/navigation_connect.js").read_text(encoding="utf-8")
        self.assertIn("function restoreNormalSurface", nav)
        self.assertIn("window.restoreChatView", nav)
        self.assertIn("restoreNormalSurface();markActiveRows()", nav)
        self.assertIn("const normal=e.target.closest?.('#persistentAgentList .agent-row:not(.sidebar-group-row)');if(normal&&state.group)leaveGroup()", nav)


if __name__ == "__main__":
    unittest.main()
