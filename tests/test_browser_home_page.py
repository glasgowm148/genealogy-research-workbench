"""Opt-in browser contract: the home page and site index read in full without JavaScript and pass axe."""
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


@unittest.skipUnless(os.environ.get('GENEALOGY_BROWSER_TESTS') == '1',
                     'Run make browser-check with the browser extra installed')
class BrowserHomePageTests(unittest.TestCase):
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
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))

    def tearDown(self):
        self.context.close()

    def axe(self):
        self.page.add_script_tag(content=Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8'))
        return self.page.evaluate("async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                                  "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
                                  ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")

    def test_a_whole_question_card_opens_its_page(self):
        self.page.goto(self.base + 'demo/index.html', wait_until='networkidle')
        card = self.page.locator('.home-question', has_text='Where did they live?')
        box = card.bounding_box()
        self.page.mouse.click(box['x'] + box['width'] - 12, box['y'] + box['height'] - 12)  # a corner, away from the heading link
        self.page.wait_for_url('**/places.html')
        self.page.goto(self.base + 'demo/index.html')
        self.page.locator('a.home-sun-link').click()
        self.page.wait_for_url('**/tree.html?person=*&view=sun')
        self.page.locator('svg[data-sun]').wait_for()
        self.assertEqual([], self.errors)

    @unittest.skipUnless(os.environ.get('GENEALOGY_AXE_PATH'), 'set GENEALOGY_AXE_PATH to an axe-core axe.min.js')
    def test_home_and_site_index_pass_axe_and_fit_both_widths(self):
        for width in (1440, 390):
            self.page.set_viewport_size({'width': width, 'height': 900})
            for site in ('demo', 'large'):
                for route in ('index.html', 'sitemap.html'):
                    with self.subTest(width=width, site=site, route=route):
                        self.page.goto(f'{self.base}{site}/{route}', wait_until='networkidle')
                        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1)
                        self.assertEqual([], self.axe())
        self.assertEqual([], self.errors)

    def test_without_javascript_the_home_page_is_complete(self):
        context = self.browser.new_context(java_script_enabled=False, viewport={'width': 390, 'height': 900})
        try:
            page = context.new_page()
            page.goto(self.base + 'demo/index.html')
            self.assertEqual(6, page.locator('.home-question').count())
            self.assertTrue(page.locator('svg.home-sun').is_visible())
            self.assertEqual(4, page.locator('.home-steps > li').count())
            self.assertIn('has the most recorded descendants', page.locator('.home-preview figcaption').inner_text())
            page.goto(self.base + 'demo/sitemap.html')
            self.assertEqual(6, page.locator('.way-in > li').count())
            self.assertEqual(6, page.locator('table.downloads tbody tr').count())  # includes the progress history
        finally:
            context.close()


if __name__ == '__main__':
    unittest.main()
