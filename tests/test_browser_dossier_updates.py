"""Opt-in browser contract: the dossier's pending tree updates read at both widths, with or without JavaScript, axe clean."""
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
from test_dossier_updates import updates_case


@unittest.skipUnless(os.environ.get('GENEALOGY_BROWSER_TESTS') == '1',
                     'Run make browser-check with the browser extra installed')
class BrowserDossierUpdatesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        config = ProjectConfig(name='Fictional updates', raw={'site': {'tree_name': 'FableTree'}})
        config.validate()
        paths = build_site(updates_case(), config, cls.root)
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

    def test_section_at_both_widths(self):
        for width in (1280, 390):
            with self.subTest(width=width):
                page = self.open(width)
                page.locator('.dossier-hero p.explore a', has_text='Pending updates').click()
                page.wait_for_function("location.hash === '#updates'")
                heading = page.locator('h2#updates')
                self.assertEqual('Pending FableTree updates', heading.inner_text().strip())
                box = heading.bounding_box()
                self.assertLess(box['y'], 900)  # the link brought it into view
                self.assertEqual(3, page.locator('.pending-updates > li').count())
                self.assertTrue(page.locator('.pending-profile a', has_text='Open on FableTree').is_visible())
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width + 1)
                if os.environ.get('GENEALOGY_AXE_PATH'):
                    page.add_script_tag(content=Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8'))
                    violations = page.evaluate(
                        "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                        "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
                        ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
                    self.assertEqual([], violations, width)

    def test_readable_without_javascript(self):
        page = self.open(390, javascript=False)
        self.assertTrue(page.locator('h2#updates').is_visible())
        self.assertIn('Significance 55 of 100', page.locator('.pending-updates').inner_text())
        self.assertEqual(['Family tree', 'Find a connection', 'Compare', 'Everyone surnamed Fable', 'Pending updates'],
                         page.locator('.dossier-hero p.explore a').all_inner_texts())


if __name__ == '__main__':
    unittest.main()
