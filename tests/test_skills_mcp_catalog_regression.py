import unittest

from agentie.core.mcp_catalog import presets
from agentie.core.skill_registry import DEFAULT_SKILLS


class SkillsMCPCatalogRegressionTests(unittest.TestCase):
    def test_core_agent_skills_have_permission_metadata(self):
        for skill_id in ("github", "browser-automation", "email", "knowledge-memory", "planning"):
            self.assertIn(skill_id, DEFAULT_SKILLS)
            self.assertTrue(DEFAULT_SKILLS[skill_id].get("capabilities"))
            self.assertTrue(DEFAULT_SKILLS[skill_id].get("permissions"))

    def test_mcp_catalog_has_curated_sources_and_permissions(self):
        items={item["id"]:item for item in presets()}
        for server_id in ("filesystem", "playwright", "github", "memory", "fetch", "git"):
            self.assertIn(server_id, items)
            self.assertEqual(items[server_id].get("source"), "curated")
            self.assertTrue(items[server_id].get("permission_groups"))

    def test_official_github_mcp_keeps_registry_identity(self):
        github={item["id"]:item for item in presets()}["github"]
        self.assertEqual(github.get("registry_name"), "io.github.github/github-mcp-server")
        self.assertIn("registry.modelcontextprotocol.io", github.get("registry_url", ""))

    def test_catalog_does_not_auto_grant_or_auto_install(self):
        for item in presets():
            self.assertNotIn("agent_ids", item)
            self.assertNotEqual(item.get("installed"), True)


if __name__ == "__main__":
    unittest.main()
