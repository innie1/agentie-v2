import gc
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import agent_registry, memory_store, role_store, semantic_memory
from agentie.core.observability import start_trace, finish_trace
from agentie.tools import approval_tools


class AgentIsolationRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patches = [
            patch.object(agent_registry, "AGENTS_FILE", root / "agents.json"),
            patch.object(role_store, "ROLES", root / "roles.json"),
            patch.object(memory_store, "DB_PATH", root / "memory.sqlite3"),
            patch.object(semantic_memory, "DB_PATH", root / "semantic.sqlite3"),
            patch.object(approval_tools, "STORE", root / "approvals.json"),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        memory_store.set_active_memory_scope("user")
        # Ensure all background semantic-memory writes that may reference the
        # temporary SQLite files have completed before restoring paths.
        try:
            memory_store._SEMANTIC_POOL.submit(lambda: None).result(timeout=10)
        except Exception:
            pass
        for item in reversed(self.patches):
            item.stop()
        # sqlite3.Connection's context manager commits/rolls back but Windows
        # can keep the underlying file handle alive until objects are collected.
        # Collect and briefly retry cleanup rather than masking real test errors.
        gc.collect()
        last_error = None
        for _ in range(10):
            try:
                self.temp.cleanup()
                return
            except (PermissionError, NotADirectoryError) as exc:
                last_error = exc
                gc.collect()
                time.sleep(0.05)
        if last_error:
            raise last_error

    def test_agent_sessions_map_user_memory_to_private_scope(self):
        alex=agent_registry.create_agent("Alex","CTO","manager")["agent"]
        writer=agent_registry.create_agent("Writer","content creator","general")["agent"]
        t1=start_trace(alex["session_prefix"]+"main","manager","remember")
        memory_store.set_memory("user","secret","alpha")
        finish_trace(t1)
        t2=start_trace(writer["session_prefix"]+"main","general","recall")
        self.assertIsNone(memory_store.get_memory("user","secret"))
        memory_store.set_memory("user","secret","beta")
        finish_trace(t2)
        memory_store.set_active_memory_scope(alex["memory_scope"])
        self.assertEqual(memory_store.get_memory("user","secret"),"alpha")
        memory_store.set_active_memory_scope(writer["memory_scope"])
        self.assertEqual(memory_store.get_memory("user","secret"),"beta")

    def test_delete_agent_purges_private_memory_chat_and_semantic_rows(self):
        alex=agent_registry.create_agent("Alex","CTO","manager")["agent"]
        session=alex["session_prefix"]+"main"
        memory_store.set_active_memory_scope(alex["memory_scope"])
        memory_store.set_memory("user","project","private")
        memory_store.add_message(session,"user","hello")
        memory_store.set_context(session,"active",{"x":1})
        # Insert one semantic row without invoking an embedding model.
        semantic_memory.init_db()
        with semantic_memory._connect() as conn:
            conn.execute("INSERT INTO semantic_items(id,kind,source_id,scope,session_id,role,text,embedding_json,importance,created_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",("test-item","memory","test-source",alex["memory_scope"],None,"memory","private","[]",1.0,"2026-01-01T00:00:00+00:00","{}"))
        result=agent_registry.delete_agent("Alex")
        self.assertTrue(result["deleted"])
        self.assertIsNone(agent_registry.get_agent("Alex"))
        with memory_store._connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM memories WHERE scope=?",(alex["memory_scope"],)).fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT count(*) FROM messages WHERE session_id LIKE ?",(alex["session_prefix"]+"%",)).fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT count(*) FROM working_context WHERE session_id LIKE ?",(alex["session_prefix"]+"%",)).fetchone()[0],0)
        with semantic_memory._connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM semantic_items WHERE scope=? OR session_id LIKE ?",(alex["memory_scope"],alex["session_prefix"]+"%" )).fetchone()[0],0)

    def test_deleting_manager_detaches_direct_reports(self):
        ceo=agent_registry.create_agent("CEO","CEO","manager")["agent"]
        alex=agent_registry.create_agent("Alex","CTO","manager",manager_id=ceo["id"])["agent"]
        agent_registry.delete_agent(ceo["id"])
        self.assertIsNone(agent_registry.get_agent("CEO"))
        self.assertIsNone(agent_registry.get_agent(alex["id"])["manager_id"])

    def test_delete_command_requires_approval_then_deletes(self):
        alex=agent_registry.create_agent("Alex","CTO","manager")["agent"]
        first=role_store.route_role_command("Delete agent Alex")
        self.assertEqual(first["card"]["type"],"approvals")
        self.assertIsNotNone(agent_registry.get_agent("Alex"))
        approval=first["card"]["items"][0]
        approval_tools.resolve_approval(approval["id"],True)
        second=role_store.route_role_command("Delete agent Alex")
        self.assertEqual(second["card"]["type"],"agent_deleted")
        self.assertIsNone(agent_registry.get_agent(alex["id"]))


if __name__ == "__main__":
    unittest.main()
