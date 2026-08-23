import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import agent_builder, agent_matching, agent_registry, agent_threads, routine_engine, routine_worker, workflow_skills
from agentie.tools import approval_tools


class AgentPlatformRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        self.patches = [
            patch.object(agent_registry, "WORKSPACE", self.root),
            patch.object(agent_registry, "AGENTS_FILE", self.root / "agents.json"),
            patch.object(workflow_skills, "WORKSPACE", self.root),
            patch.object(workflow_skills, "SKILLS_DIR", self.root / "skills"),
            patch.object(routine_engine, "WORKSPACE", self.root),
            patch.object(routine_engine, "ROUTINES", self.root / "routines.json"),
            patch.object(routine_engine, "RUNS", self.root / "routine_runs.json"),
            patch.object(routine_worker, "WORKSPACE", self.root),
            patch.object(routine_worker, "EVENTS", self.root / "routine_events.json"),
            patch.object(agent_threads, "WORKSPACE", self.root),
            patch.object(agent_threads, "THREADS", self.root / "agent_threads.json"),
            patch.object(approval_tools, "STORE", self.root / "approvals.json"),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_legacy_base_name_does_not_classify_user_created_agent(self):
        agent = agent_registry.create_agent("Gemma", "Chief of Staff", "manager")["agent"]
        self.assertEqual(agent["base"], "general")
        self.assertEqual(agent["runtime_profile"], "general")
        self.assertEqual(agent["permissions"]["capability_mode"], "shared")
        self.assertFalse(agent["permissions"]["delegate"])

    def test_builder_keeps_job_ownership_separate_from_runtime_and_permissions(self):
        draft = agent_builder.draft_agent_spec(
            "Handle customer support on Gmail and WhatsApp, escalate refunds, and send a daily summary.",
            name="Ada",
            job="Customer care owner",
        )
        self.assertEqual(draft["runtime_profile"], "general")
        self.assertFalse(draft["can_delegate"])
        spec = agent_builder.normalize_create_spec({**draft, "can_delegate": True})
        self.assertEqual(spec["runtime_profile"], "general")
        self.assertTrue(spec["can_delegate"])
        self.assertEqual(spec["role"], "Customer care owner")

    def test_identity_matching_excludes_common_tools_from_knowledge_relevance(self):
        finance = agent_registry.create_agent("Fina", "Finance Agent")["agent"]
        identity = agent_matching.agent_identity_text(finance).lower()
        self.assertIn("finance", identity)
        self.assertNotIn("browser automation", identity)
        self.assertNotIn("code execution", identity)
        self.assertGreater(agent_matching.match_identity_score("finance rent budget", finance), 0)

    def test_real_workflow_skill_has_complete_reusable_contract(self):
        skill = workflow_skills.create_workflow_skill(
            name="Invoice Review",
            when_to_use="When an invoice needs checking before payment",
            required_inputs=["invoice"],
            required_access=["files"],
            steps=["Read the invoice", "Check totals", "Flag anomalies"],
            decision_rules=["Do not approve an unexplained mismatch"],
            expected_output="A concise review with risks",
            validation_rules=["Totals must reconcile"],
            approval_boundaries=["Payment always requires approval"],
            failure_handling="Stop and ask for the missing invoice",
            status="active",
        )
        self.assertEqual(skill["kind"], "workflow")
        self.assertEqual(skill["status"], "active")
        self.assertEqual(skill["required_inputs"], ["invoice"])
        self.assertEqual(len(skill["steps"]), 3)
        self.assertTrue(skill["decision_rules"])
        self.assertTrue(skill["validation_rules"])
        self.assertTrue(skill["approval_boundaries"])
        self.assertTrue(skill["failure_handling"])

    def test_taught_workflow_becomes_reviewable_skill_draft(self):
        skill = workflow_skills.draft_skill_from_taught_workflow({
            "id": "wf_123",
            "name": "Post weekly report",
            "steps": [
                {"command": "Open dashboard", "metadata": {}},
                {"command": "Fill password", "metadata": {"requires_input": True, "field": "password"}},
            ],
        })
        self.assertEqual(skill["source_workflow_id"], "wf_123")
        self.assertEqual(skill["status"], "draft")
        self.assertIn("password", " ".join(skill["required_inputs"]).lower())
        self.assertTrue(any("approval" in x.lower() for x in skill["approval_boundaries"]))

    def test_routine_is_owned_by_actual_created_agent(self):
        agent = agent_registry.create_agent("Ada", "Customer care owner")["agent"]
        routine, created = routine_engine.create_routine(
            "Create a routine called Daily Inbox that every day at 9 AM check customer messages",
            owner_agent_id=agent["id"],
        )
        self.assertTrue(created)
        self.assertEqual(routine["owner_agent_id"], agent["id"])
        self.assertEqual(routine["owner_agent_name"], "Ada")
        self.assertEqual(routine_engine.list_routines(agent["id"])[0]["id"], routine["id"])

    def test_agent_group_chat_persists_user_selected_participants(self):
        ada = agent_registry.create_agent("Ada", "Customer care owner")["agent"]
        ben = agent_registry.create_agent("Ben", "Order follow-up owner")["agent"]
        thread = agent_threads.create_thread("Customer Ops", [ada["id"], ben["name"]])
        self.assertEqual(set(thread["participant_ids"]), {ada["id"], ben["id"]})
        agent_threads.post_message(thread["id"], "user", None, "User", "Review today's support issues")
        saved = agent_threads.get_thread(thread["id"])
        self.assertEqual(saved["messages"][-1]["message"], "Review today's support issues")

    def test_background_plugin_approval_surfaces_once_through_existing_approval_card(self):
        approval = approval_tools.create_background_mcp_approval(
            "mcp:gmail:send_email:{}",
            "Allow Ada to send an email.",
            agent_id="agt_ada",
            agent_name="Ada",
            server="gmail",
            tool="send_email",
            command="gmail/send_email",
        )
        with patch.object(routine_worker, "poll_job_completion_events", return_value=[]), patch.object(routine_worker, "poll_team_completion_events", return_value=[]):
            first = routine_worker.poll_routine_events()
            second = routine_worker.poll_routine_events()
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["card"]["type"], "approvals")
        self.assertEqual(first[0]["card"]["items"][0]["id"], approval["id"])
        self.assertEqual(second, [])

    def test_platform_ui_and_api_expose_primitives_not_base_agent_choices(self):
        main = Path("main.py").read_text(encoding="utf-8")
        ui = Path("frontend/platform.js").read_text(encoding="utf-8")
        self.assertIn('PLATFORM_JS=FRONTEND_DIR/"platform.js"', main)
        self.assertIn('/agent-builder/draft', main)
        self.assertIn('/agent-builder/create', main)
        self.assertIn('/workflow-skills', main)
        self.assertIn('/agent-threads', main)
        self.assertIn('Describe the job you want this agent to own', ui)
        self.assertIn('Create reusable Skill', ui)
        self.assertIn('Agent chats', ui)
        self.assertIn('.base-agent-label,#agentType{display:none!important}', ui)

    def test_new_platform_cards_render_without_raw_json_fallback(self):
        cards = Path("frontend/cards.js").read_text(encoding="utf-8")
        self.assertIn("workflow_skill:renderWorkflowSkill", cards)
        self.assertIn("agent_thread:renderAgentThread", cards)
        self.assertIn("agent_threads:renderAgentThreads", cards)
        self.assertIn("owner_agent_name", cards)
        self.assertIn("Approval boundaries", cards)

    def test_persistent_runtime_uses_shared_capability_checks_not_job_title_tool_bundles(self):
        source = Path("agentie/tools/persistent_tools.py").read_text(encoding="utf-8")
        access = Path("agentie/core/agent_access.py").read_text(encoding="utf-8")
        self.assertIn("skill_allowed(agent", source)
        self.assertIn("mcp_allowed(agent", source)
        self.assertIn("use_plugin", source)
        self.assertIn('return global_skill_allowed(skill_id)',access)
        self.assertIn('return global_mcp_allowed(name)',access)
        self.assertNotIn('agent.get("base")', source)
        self.assertNotIn('agent.get("role")', source)


if __name__ == "__main__":
    unittest.main()
