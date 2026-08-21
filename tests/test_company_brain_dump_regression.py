import gc
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import agent_registry, company_knowledge, memory_store, project_brain, semantic_memory
from agentie.tools import approval_tools


class CompanyBrainDumpRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        self.patches = [
            patch.object(agent_registry, "WORKSPACE", self.root),
            patch.object(agent_registry, "AGENTS_FILE", self.root / "agents.json"),
            patch.object(memory_store, "WORKSPACE", self.root),
            patch.object(memory_store, "DB_PATH", self.root / "memory.sqlite3"),
            patch.object(memory_store, "_SEMANTIC_BOOTSTRAPPED", False),
            patch.object(memory_store, "_semantic_async", lambda *args, **kwargs: None),
            patch.object(semantic_memory, "WORKSPACE", self.root),
            patch.object(semantic_memory, "DB_PATH", self.root / "semantic.sqlite3"),
            patch.object(project_brain, "WORKSPACE", self.root),
            patch.object(project_brain, "PROJECTS_FILE", self.root / "projects.json"),
            patch.object(approval_tools, "STORE", self.root / "approvals.json"),
        ]
        for item in self.patches:
            item.start()
        self.chief = agent_registry.create_agent("Gemma", "Chief of Staff", "manager")["agent"]
        self.finance = agent_registry.create_agent("Fina", "Finance Agent", "general")["agent"]
        self.marketing = agent_registry.create_agent("Maya", "Marketing Agent", "general")["agent"]
        self.ops = agent_registry.create_agent("Owen", "Operations Agent", "general")["agent"]

    def tearDown(self):
        memory_store.set_active_memory_scope("user")
        try:
            memory_store._SEMANTIC_POOL.submit(lambda: None).result(timeout=30)
        except Exception:
            pass
        for item in reversed(self.patches):
            item.stop()
        gc.collect()
        time.sleep(0.05)
        self.temp.cleanup()

    def test_plain_conversation_is_not_blindly_saved_as_company_knowledge(self):
        result = company_knowledge.route_company_knowledge_command("We started a laundry business")
        self.assertIsNone(result)
        self.assertEqual(memory_store.list_memories("company", 50), [])

    def test_explicit_brain_dump_extracts_and_routes_by_role(self):
        result = company_knowledge.route_company_knowledge_command(
            "Brain dump: We started a laundry business. Rent is ₦300000 yearly. "
            "We want to target students and offices. We have one washing machine."
        )
        self.assertEqual(result["card"]["type"], "company_knowledge")
        items = result["card"]["items"]
        self.assertGreaterEqual(len(items), 4)
        rent = next(item for item in items if "Rent" in item["value"])
        target = next(item for item in items if "students" in item["value"])
        machine = next(item for item in items if "washing machine" in item["value"])
        self.assertIn("finance", rent["categories"])
        self.assertIn("Fina", rent["shared_with"])
        self.assertIn("Gemma", rent["shared_with"])
        self.assertIn("marketing", target["categories"])
        self.assertIn("Maya", target["shared_with"])
        self.assertIn("operations", machine["categories"])
        self.assertIn("Owen", machine["shared_with"])
        self.assertEqual(result["card"]["routed_by"], "Gemma")

    def test_company_context_is_role_scoped_and_manager_can_see_all(self):
        company_knowledge.ingest_company_brain_dump(
            "Rent is ₦300000 yearly. We want to target students and offices. We have one washing machine."
        )
        finance = company_knowledge.company_context_for_agent(self.finance, "What are our rent and costs?", 8)
        marketing = company_knowledge.company_context_for_agent(self.marketing, "Who are we targeting?", 8)
        manager = company_knowledge.company_context_for_agent(self.chief, "Tell me about the laundry business", 8)
        self.assertIn("₦300000", finance)
        self.assertNotIn("target students", finance)
        self.assertIn("target students", marketing)
        self.assertNotIn("washing machine", marketing)
        self.assertIn("₦300000", manager)
        self.assertIn("target students", manager)
        self.assertIn("washing machine", manager)

    def test_user_can_update_company_knowledge_without_creating_duplicate_store(self):
        item = company_knowledge.add_company_knowledge("Rent is ₦300000 yearly")
        result = company_knowledge.route_company_knowledge_command(
            f"Update company knowledge {item['id']} to Rent is ₦350000 yearly"
        )
        self.assertEqual(result["card"]["type"], "company_knowledge")
        rows = memory_store.list_memories("company", 50)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["key"], item["id"])
        self.assertIn("₦350000", rows[0]["value"])

    def test_company_knowledge_delete_uses_existing_approval_and_executes_on_approval(self):
        item = company_knowledge.add_company_knowledge("Rent is ₦300000 yearly")
        first = company_knowledge.route_company_knowledge_command(f"Delete company knowledge {item['id']}")
        self.assertEqual(first["card"]["type"], "approvals")
        approval = first["card"]["items"][0]
        self.assertEqual(approval["metadata"]["kind"], "company_knowledge_delete")
        resolved = approval_tools.resolve_approval(approval["id"], True)
        self.assertEqual(resolved["status"], "consumed")
        self.assertTrue(resolved["execution_result"]["deleted"])
        self.assertEqual(memory_store.list_memories("company", 50), [])

    def test_project_brain_dump_reuses_existing_project_knowledge(self):
        project = project_brain.create_project("Laundry", "Launch and grow a laundry business", "business")
        result = company_knowledge.route_company_knowledge_command(
            "Brain dump for project Laundry: Rent is ₦300000 yearly. Target students near campus."
        )
        self.assertEqual(result["card"]["type"], "project")
        saved = project_brain.get_project(project["id"])
        self.assertEqual(len(saved["knowledge"]), 2)
        self.assertTrue(all(item.get("shared") for item in saved["knowledge"]))
        self.assertTrue(any("finance" in item.get("categories", []) for item in saved["knowledge"]))
        self.assertTrue(any("marketing" in item.get("categories", []) for item in saved["knowledge"]))

    def test_existing_memory_context_injects_relevant_company_knowledge(self):
        company_knowledge.add_company_knowledge("Rent is ₦300000 yearly")
        session = f"{self.finance['session_prefix']}main"
        prompt = memory_store.build_context_prompt(session, "What are our rent costs?")
        self.assertIn("Relevant shared company knowledge", prompt)
        self.assertIn("₦300000", prompt)

    def test_router_and_ui_use_real_company_knowledge_controls(self):
        router = Path("agentie/core/advanced_local_router.py").read_text(encoding="utf-8")
        self.assertIn("route_company_knowledge_command", router)
        self.assertLess(router.index("route_company_knowledge_command(text)"), router.index("_memory_command(text)"))
        cards = Path("frontend/cards.js").read_text(encoding="utf-8")
        index = Path("frontend/index.html").read_text(encoding="utf-8")
        approvals = Path("agentie/tools/approval_tools.py").read_text(encoding="utf-8")
        self.assertIn("company_knowledge", cards)
        self.assertIn("Update company knowledge ${item.id}", cards)
        self.assertIn("Delete company knowledge ${item.id}", cards)
        self.assertIn("c.type==='company_knowledge'", index)
        self.assertIn("data-company-edit", index)
        self.assertIn("data-company-delete", index)
        self.assertLess(index.index("c.type==='company_knowledge'"), index.index("shell('Agentie result')"))
        self.assertIn('kind == "company_knowledge_delete"', approvals)
        self.assertIn("delete_company_knowledge", approvals)


if __name__ == "__main__":
    unittest.main()
