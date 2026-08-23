import unittest
from pathlib import Path


class FrontendObserverPerformanceRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loader = Path('frontend/create_menu_loader.js').read_text(encoding='utf-8')

    def test_shared_tool_catalog_has_no_competing_background_observer(self):
        self.assertIn('function ensureSharedToolCatalog()', self.loader)
        self.assertIn('if(pluginPanel)ensureSharedToolCatalog()', self.loader)
        self.assertIn("setTimeout(ensureSharedToolCatalog,180)", self.loader)
        self.assertNotIn('new MutationObserver', self.loader)
        self.assertNotIn('MutationObserver(', self.loader)

    def test_profile_polish_is_user_event_driven_not_background_dom_scanning(self):
        self.assertIn('function polishOpenProfiles()', self.loader)
        self.assertIn('function scheduleProfilePolish()', self.loader)
        self.assertIn("document.addEventListener('click',scheduleProfilePolish,false)", self.loader)
        self.assertIn('setTimeout(()=>{polishTimerA=null;polishOpenProfiles()},0)', self.loader)
        self.assertIn('setTimeout(()=>{polishTimerB=null;polishOpenProfiles()},160)', self.loader)
        self.assertNotIn('profileObserver', self.loader)
        self.assertNotIn('polishAddedNode', self.loader)

    def test_profile_polish_remains_idempotent(self):
        self.assertIn("card.dataset.agentiePolished='1'", self.loader)
        self.assertIn("form.dataset.agentieUnified==='1'", self.loader)
        self.assertIn("if(save.textContent!=='Save details')", self.loader)
        self.assertIn("actions.querySelector('.agentie-profile-delete')", self.loader)


if __name__ == '__main__':
    unittest.main()
