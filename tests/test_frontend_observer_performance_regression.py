import unittest
from pathlib import Path


class FrontendObserverPerformanceRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loader = Path('frontend/create_menu_loader.js').read_text(encoding='utf-8')

    def test_shared_tool_catalog_does_not_use_competing_mutation_observer(self):
        self.assertIn('function ensureSharedToolCatalog()', self.loader)
        self.assertNotIn('new MutationObserver(ensureSharedToolCatalog)', self.loader)
        self.assertIn("setTimeout(ensureSharedToolCatalog,180)", self.loader)
        self.assertIn('two observers that remove/recreate each other', self.loader)

    def test_profile_observer_only_processes_added_profile_modals(self):
        self.assertIn('function polishAddedNode(node)', self.loader)
        self.assertIn('for(const node of record.addedNodes)polishAddedNode(node)', self.loader)
        self.assertNotIn("new MutationObserver(()=>document.querySelectorAll('.employee-profile-modal').forEach(polishAgentProfile))", self.loader)
        self.assertIn("card.dataset.agentiePolished!=='1'", self.loader)
        self.assertIn("edit&&edit.textContent.trim()!=='Edit details'", self.loader)

    def test_profile_polish_is_idempotent(self):
        self.assertIn("card.dataset.agentiePolished='1'", self.loader)
        self.assertIn("form.dataset.agentieUnified==='1'", self.loader)
        self.assertIn("if(save.textContent!=='Save details')", self.loader)


if __name__ == '__main__':
    unittest.main()
