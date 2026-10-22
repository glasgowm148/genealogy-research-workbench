"""Opt-in browser contract: the dossier hero sits beside its latest finding on wide screens and stacks on phones."""
from __future__ import annotations

from functools import partial
from http.server import ThreadingHTTPServer
import os
from pathlib import Path
import tempfile
import threading
import unittest

from genealogy.config import ProjectConfig
from genealogy.site import build_site
from test_browser_site import QuietHandler  # tests/ is on the path under unittest discovery
from test_dossier_hero import hero_case


@unittest.skipUnless(os.environ.get('GENEALOGY_BROWSER_TESTS') == '1',
                     'Run make browser-check with the browser extra installed')
class BrowserDossierHeroTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        config = ProjectConfig(name='Fictional heroes', raw={'site': {'contact_email': 'corrections@example.invalid'}})
        config.validate()
        paths = build_site(hero_case(), config, cls.root)
        cls.ada = next(key for key, path in paths.items() if key.startswith('people/') and 'data-person-id="ada"' in path.read_text())
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(cls.root)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}/'
        cls.pw = sync_playwright().start()
        executable = os.environ.get('GENEALOGY_BROWSER_EXECUTABLE')
        cls.browser = cls.pw.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def open(self, width, javascript=True):
        context = self.browser.new_context(viewport={'width': width, 'height': 900}, java_script_enabled=javascript)
        self.addCleanup(context.close)
        page = context.new_page()
        page.goto(self.base + self.ada, wait_until='networkidle')
        return page

    def test_hero_layout_wide_and_stacked(self):
        for width in (1280, 390):
            with self.subTest(width=width):
                page = self.open(width)
                main, aside = page.locator('.dossier-hero-main').bounding_box(), page.locator('.dossier-hero .latest-finding').bounding_box()
                if width > 640:
                    self.assertGreaterEqual(aside['x'], main['x'] + main['width'] - 1)  # beside the main column
                    self.assertLess(abs(aside['y'] - main['y']), 40)
                else:
                    self.assertGreaterEqual(aside['y'], main['y'] + main['height'] - 1)  # stacked below it
                vitals = page.locator('.vitals dt')
                self.assertEqual(['Born', 'Died'], vitals.all_text_contents())
                # The save control joins the other actions rather than trailing the page.
                self.assertEqual(1, page.locator('.dossier-actions button[aria-pressed]').count())
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width + 1)
                if os.environ.get('GENEALOGY_AXE_PATH'):
                    page.add_script_tag(content=Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8'))
                    violations = page.evaluate(
                        "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                        "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
                        ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
                    self.assertEqual([], violations, width)

    def test_connected_groups_open_without_javascript(self):
        page = self.open(1280, javascript=False)
        self.assertEqual(['Family tree', 'Find a connection', 'Compare', 'Everyone surnamed Fable'],
                         page.locator('.dossier-hero p.explore a').all_inner_texts())
        group = page.locator('details.connected-group', has_text='Places')
        link = group.get_by_role('link', name='Invented Parish')
        self.assertFalse(link.is_visible())
        group.locator('summary').click()
        self.assertTrue(link.is_visible())
        link.click()
        page.wait_for_url('**/places/pl-*.html')
        self.assertEqual('Invented Parish', page.locator('h1').inner_text())


if __name__ == '__main__':
    unittest.main()
