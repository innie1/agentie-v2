import unittest
from pathlib import Path


class VisualPreviewPluginSearchRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("frontend/plugin_setup.js").read_text(encoding="utf-8")

    def test_plugins_page_has_live_search_input(self):
        self.assertIn("plugins-search", self.source)
        self.assertIn("type='search'", self.source)
        self.assertIn("Search plugins, MCPs and capabilities", self.source)
        self.assertIn("Search plugins and MCPs", self.source)

    def test_plugin_search_filters_existing_plugin_rows_by_visible_metadata(self):
        self.assertIn("querySelectorAll('.mcp-row')", self.source)
        self.assertIn("norm(row.textContent).includes(q)", self.source)
        self.assertIn("No plugins or MCPs match your search.", self.source)

    def test_plugin_search_survives_plugin_panel_refreshes(self):
        self.assertIn("let query=''", self.source)
        self.assertIn("input.value=query", self.source)
        self.assertIn("new MutationObserver", self.source)
        self.assertIn("ensure()", self.source)

    def test_existing_plugin_configure_and_secret_clear_ux_are_preserved(self):
        self.assertIn("augmentPluginRows", self.source)
        self.assertIn("configure.textContent='Configure'", self.source)
        self.assertIn("Clear saved secret?", self.source)
        self.assertIn("confirmClearSetup", self.source)

    def test_visual_file_cards_gain_view_for_svg_and_html(self):
        self.assertIn("dataInlineView", self.source.replace("data-inline-view", "dataInlineView"))
        self.assertIn("lower.endsWith('.svg')", self.source)
        self.assertIn("lower.endsWith('.html')", self.source)
        self.assertIn("b.textContent='View'", self.source)

    def test_svg_preview_renders_inline_as_an_image(self):
        self.assertIn("image/svg+xml", self.source)
        self.assertIn("document.createElement('img')", self.source)
        self.assertIn("img.loading='lazy'", self.source)
        self.assertIn("Diagram preview", self.source)

    def test_motion_html_preview_is_sandboxed_and_blocks_network_access(self):
        self.assertIn("document.createElement('iframe')", self.source)
        self.assertIn("setAttribute('sandbox','allow-scripts')", self.source)
        self.assertIn("connect-src 'none'", self.source)
        self.assertIn("frame-src 'none'", self.source)
        self.assertIn("referrerPolicy='no-referrer'", self.source)
        self.assertIn("Motion graphic preview", self.source)

    def test_preview_reuses_existing_download_route_instead_of_new_backend(self):
        self.assertIn("a[href^=\"/files/\"][href$=\"/download\"]", self.source)
        self.assertIn("await fetch(info.href", self.source)
        self.assertNotIn("/files/preview", self.source)

    def test_inspect_updates_same_card_instead_of_appending_duplicate_file_card(self):
        self.assertIn("event.stopImmediatePropagation()", self.source)
        self.assertIn("body:JSON.stringify({action:'inspect'})", self.source)
        self.assertIn("status(card,parts.join(' · '))", self.source)
        inspect_block = self.source.split("document.addEventListener('click',async event=>", 1)[1]
        inspect_block = inspect_block.split("},true);", 1)[0]
        self.assertNotIn("window.addAssistant", inspect_block)


if __name__ == "__main__":
    unittest.main()
