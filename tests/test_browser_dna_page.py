"""Opt-in browser contract: the DNA page and its branch pages read at both widths, pass axe and need no script."""
from __future__ import annotations

from functools import partial
from http.server import ThreadingHTTPServer
import os
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import urlsplit

from genealogy.config import ProjectConfig
from genealogy.site import _key, build_site
from test_browser_site import QuietHandler  # tests/ is on the path under unittest discovery
from test_dna_page import dna_case


@unittest.skipUnless(os.environ.get('GENEALOGY_BROWSER_TESTS') == '1',
                     'Run make browser-check with the browser extra installed')
class BrowserDnaPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        build_site(dna_case(), ProjectConfig(name='Fictional DNA', raw={'site': {'dna_heading': 'Y-DNA'}}), cls.root)
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
        self.errors, self.external = [], []
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))
        def route(request):
            if urlsplit(request.request.url).hostname not in ('127.0.0.1', None):
                self.external.append(request.request.url)
                request.abort()
            else:
                request.continue_()
        self.page.route('**/*', route)

    def tearDown(self):
        self.context.close()
        self.assertEqual([], self.errors, 'Browser runtime errors')
        self.assertEqual([], self.external, 'Public site must work without outside requests')

    def axe(self):
        self.page.add_script_tag(content=Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8'))
        return self.page.evaluate("async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                                  "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations"
                                  ".map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")

    def test_the_chain_is_a_row_of_links_to_the_branch_pages(self):
        self.page.goto(self.base + 'dna.html', wait_until='networkidle')
        chain = self.page.get_by_role('group', name='Branch chain: each branch under the one it descends from')
        self.assertEqual(4, chain.get_by_role('link').count())
        chain.get_by_role('link', name='R-FABLE2, c. 1300 CE').focus()
        self.page.keyboard.press('Enter')
        self.page.wait_for_url('**/dna/r-fable2.html')
        self.assertEqual('R-FABLE2', self.page.locator('h1').inner_text())
        # The branch page's own chain marks it current and leads on to the branch below.
        line = self.page.get_by_role('group', name='Line of descent of R-FABLE2')
        self.assertEqual('page', line.locator('[aria-current]').get_attribute('aria-current'))
        line.get_by_role('link', name='R-FABLE3', exact=True).click()
        self.page.wait_for_url('**/dna/r-fable3.html')
        self.page.get_by_role('link', name='Ada Fable').click()
        self.page.wait_for_url(f'**/people/p-{_key("ada")}.html')
        self.assertIn('Y-DNA: R-FABLE3 · reported root', self.page.locator('.dna-line').inner_text())

    def test_readable_without_javascript(self):
        context = self.browser.new_context(java_script_enabled=False)
        try:
            page = context.new_page()
            page.goto(self.base + 'dna.html')
            self.assertEqual(['The genetic structure', 'Documentary lines', 'Interpretation'], page.locator('main h2').all_inner_texts())
            self.assertEqual(4, page.locator('.dna-tree a').count())
            self.assertTrue(page.locator('svg.dna-chain').is_visible())
            self.assertEqual(3, page.locator('table.dna-lines tbody tr').count())
            page.goto(self.base + 'dna/r-fable3.html')
            self.assertEqual(2, page.locator('table.dna-lines tbody tr').count())
        finally:
            context.close()

    def test_both_widths_pass_axe_without_sideways_scrolling(self):
        for width in (1440, 390):
            self.page.set_viewport_size({'width': width, 'height': 900})
            for path in ('dna.html', 'dna/r-fable1.html', 'dna/r-fable3.html', f'people/p-{_key("ada")}.html'):
                with self.subTest(width=width, path=path):
                    self.page.goto(self.base + path, wait_until='networkidle')
                    self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1)
                    if path.startswith('dna'):
                        box = self.page.locator('svg.dna-chain').bounding_box()
                        self.assertLessEqual(box['x'] + box['width'], width)
                    if os.environ.get('GENEALOGY_AXE_PATH'):
                        self.assertEqual([], self.axe())


if __name__ == '__main__':
    unittest.main()
