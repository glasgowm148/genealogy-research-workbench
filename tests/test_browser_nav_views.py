"""Opt-in browser check: the catalogue marks the saved view its address carries as the current page."""
from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest

from genealogy.case import CaseStore
from genealogy.config import ProjectConfig
from genealogy.site import build_site

ROOT = Path(__file__).resolve().parents[1]
CURRENT = "[...document.querySelectorAll('.nav-section ul a[aria-current]')].map(a => [a.textContent, a.getAttribute('aria-current')])"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@unittest.skipUnless(os.environ.get('GENEALOGY_BROWSER_TESTS') == '1', 'Run make browser-check with the browser extra installed')
class CatalogueViewsBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        config = ProjectConfig.load(ROOT / 'examples/demo/genealogy.toml')
        cls.labels = [label for label, _ in config.catalogue_views]
        build_site(CaseStore(ROOT / 'examples/demo/cases').load(config.default_case), config, root)
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(root)))
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
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))

    def tearDown(self):
        self.context.close()
        self.assertEqual([], self.errors, 'Browser runtime errors')

    def open(self, path):
        self.page.goto(self.base + path, wait_until='networkidle')
        self.page.locator('.result-count').wait_for()

    def current(self):
        return self.page.evaluate(CURRENT)

    def test_the_view_the_address_carries_is_current(self):
        self.open('catalogue.html')
        self.assertEqual([['People catalogue', 'page']], self.current())
        self.open('catalogue.html?no_external=1')
        self.assertEqual([[self.labels[0], 'page']], self.current())
        # The same parameters in another order are the same view.
        self.open('catalogue.html?year_to=1799&date_type=birth')
        self.assertEqual([[self.labels[1], 'page']], self.current())
        # A view's link opens it.
        self.page.get_by_role('link', name=self.labels[0], exact=True).click()
        self.page.wait_for_url('**/catalogue.html?no_external=1')
        self.page.locator('.result-count').wait_for()
        self.assertEqual([[self.labels[0], 'page']], self.current())

    def test_changing_the_search_leaves_the_view_and_returning_restores_it(self):
        self.open('catalogue.html?no_external=1')
        search = self.page.locator('#catalogue-query')
        search.fill('Alderwick')
        self.page.wait_for_function("() => location.search.includes('q=')")
        self.page.wait_for_function(f"() => JSON.stringify({CURRENT}) === JSON.stringify({json.dumps([['People catalogue', 'page']])})")
        search.fill('')
        self.page.wait_for_function(f"() => JSON.stringify({CURRENT}) === JSON.stringify({json.dumps([[self.labels[0], 'page']])})")
        # Another filter on top is no longer exactly the view.
        self.open('catalogue.html?no_external=1&sex=F')
        self.assertEqual([['People catalogue', 'page']], self.current())

    def test_other_people_pages_mark_no_view(self):
        self.page.goto(self.base + 'branches.html?no_external=1', wait_until='networkidle')
        self.assertEqual([['Families & branches', 'page']], self.current())

    def test_axe_with_a_view_current(self):
        if not os.environ.get('GENEALOGY_AXE_PATH'):
            self.skipTest('GENEALOGY_AXE_PATH is not set')
        self.open('catalogue.html?no_external=1')
        self.page.add_script_tag(content=Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8'))
        violations = self.page.evaluate(
            "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
            "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations.map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
        self.assertEqual([], violations)


if __name__ == '__main__':
    unittest.main()
