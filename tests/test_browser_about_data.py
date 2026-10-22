"""Opt-in browser contract: About the data, the change log and the described downloads read well and pass axe."""
from __future__ import annotations

from functools import partial
from http.server import ThreadingHTTPServer
import os
from pathlib import Path
import tempfile
import threading
import unittest

from genealogy.case import CaseStore
from genealogy.config import ProjectConfig
from genealogy.site import build_site
from test_browser_site import ROOT, QuietHandler  # tests/ is on the path under unittest discovery

PAGES = ('about-data.html', 'changes.html', 'sitemap.html')


@unittest.skipUnless(os.environ.get('GENEALOGY_BROWSER_TESTS') == '1',
                     'Run make browser-check with the browser extra installed')
class BrowserAboutDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        from test_scale import large_case
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        config = ProjectConfig.load(ROOT / 'examples/demo/genealogy.toml')
        build_site(CaseStore(ROOT / 'examples/demo/cases').load(config.default_case), config, cls.root / 'demo')
        build_site(large_case(), ProjectConfig(name='Fictional large tree'), cls.root / 'large')
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

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1440, 'height': 1000})
        self.page = self.context.new_page()

    def tearDown(self):
        self.context.close()

    def test_pages_read_without_javascript_and_fit_a_phone(self):
        context = self.browser.new_context(viewport={'width': 390, 'height': 900}, java_script_enabled=False)
        page = context.new_page()
        try:
            for site in ('demo', 'large'):
                for route in PAGES:
                    with self.subTest(site=site, route=route):
                        page.goto(self.base + f'{site}/{route}')
                        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 391)
            page.goto(self.base + 'demo/about-data.html')
            self.assertEqual(4, page.locator('.about-counts .stat').count())
            self.assertEqual(4, page.locator('.about-totals tbody tr').count())
            self.assertTrue(page.locator('.legend-badges a.evidence-badge').first.is_visible())
            page.goto(self.base + 'demo/changes.html')
            self.assertGreaterEqual(page.locator('.change-card').count(), 2)
            self.assertTrue(page.get_by_role('link', name='Latest findings →').is_visible())
            page.goto(self.base + 'demo/sitemap.html#downloads')
            self.assertGreaterEqual(page.locator('table.downloads tbody tr').count(), 5)
        finally:
            context.close()

    def test_change_cards_sit_three_to_a_row_on_a_wide_screen(self):
        self.page.goto(self.base + 'demo/changes.html')
        tops = self.page.evaluate("[...document.querySelectorAll('.change-card')].slice(0, 3).map(c => Math.round(c.getBoundingClientRect().top))")
        self.assertEqual(1, len(set(tops)), tops)

    @unittest.skipUnless(os.environ.get('GENEALOGY_AXE_PATH'), 'set GENEALOGY_AXE_PATH to an axe-core axe.min.js')
    def test_pages_pass_axe_at_both_widths(self):
        axe = Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8')
        for width in (1440, 390):
            self.page.set_viewport_size({'width': width, 'height': 900})
            for site in ('demo', 'large'):
                for route in PAGES:
                    with self.subTest(width=width, site=site, route=route):
                        self.page.goto(self.base + f'{site}/{route}', wait_until='networkidle')
                        self.page.add_script_tag(content=axe)
                        violations = self.page.evaluate(
                            "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                            "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
                            ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
                        self.assertEqual([], violations)


if __name__ == '__main__':
    unittest.main()
