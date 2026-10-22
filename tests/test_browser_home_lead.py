"""Opt-in browser contract: the home page's priority studies, featured question, studies and lead-ins read without JavaScript and fit a phone."""
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
class BrowserHomeLeadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        config = ProjectConfig.load(ROOT / 'examples/demo/genealogy.toml')
        build_site(CaseStore(ROOT / 'examples/demo/cases').load(config.default_case), config, cls.root)
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

    def test_without_javascript_every_section_shows_at_both_widths(self):
        for width in (1440, 390):
            context = self.browser.new_context(java_script_enabled=False, viewport={'width': width, 'height': 900})
            try:
                page = context.new_page()
                page.goto(self.base + 'index.html')
                with self.subTest(width=width):
                    self.assertTrue(page.locator('svg.home-priority-map').is_visible())
                    self.assertEqual(3, page.locator('.home-priority-place').count())
                    self.assertEqual(['1', '2', '3'], page.locator('.home-priority-number').all_inner_texts())
                    question = page.locator('.home-featured-question')
                    self.assertIn('Which invented household return', question.locator('h2').inner_text())  # [home] featured_question
                    self.assertEqual(4, question.locator('.home-question-facts > li').count())
                    self.assertEqual(1, page.locator('.home-study').count())
                    self.assertEqual(2, page.locator('.home-resource').count())
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width + 1)
                    # The map sits beside the list on a wide screen and above it on a phone.
                    figure, listing = page.locator('.home-priority-figure').bounding_box(), page.locator('.home-priority-list').bounding_box()
                    self.assertEqual(width > 850, listing['x'] > figure['x'] + figure['width'] - 1)
                page.locator('.home-featured-question a', has_text='Read the research').click()
                page.wait_for_url('**/people/*.html#research')
            finally:
                context.close()


if __name__ == '__main__':
    unittest.main()
