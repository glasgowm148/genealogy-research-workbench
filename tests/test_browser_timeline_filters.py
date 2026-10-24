"""Opt-in browser contract for timeline range filters and shareable state."""
from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@unittest.skipUnless(os.environ.get('GENEALOGY_BROWSER_TESTS') == '1', 'browser tests disabled')
class TimelineFilterBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from genealogy.case import CaseStore
        from genealogy.config import ProjectConfig
        from genealogy.models import AccessLevel, Event
        from genealogy.site import build_site
        config = ProjectConfig.load(ROOT / 'examples/demo/genealogy.toml')
        case = CaseStore(ROOT / 'examples/demo/cases').load(config.default_case)
        case.add_many([
            Event('timeline-signed', 'milestone', date='-0044', sensitivity=AccessLevel.PUBLIC),
            Event('timeline-undated', 'milestone', sensitivity=AccessLevel.PUBLIC),
            Event('timeline-modern', 'milestone', date='1900', sensitivity=AccessLevel.PUBLIC),
        ])
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        build_site(case, config, cls.root / 'site')
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(cls.root)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}/site/'
        from playwright.sync_api import sync_playwright
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.pw.stop(); cls.server.shutdown(); cls.server.server_close(); cls.thread.join(); cls.temp.cleanup()

    def setUp(self):
        self.context = self.browser.new_context(); self.page = self.context.new_page(); self.errors = []
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))

    def tearDown(self):
        self.context.close(); self.assertEqual([], self.errors)

    def test_combined_range_url_reload_and_reset(self):
        self.page.goto(self.base + 'timeline.html')
        self.page.get_by_role('spinbutton', name='From year').fill('1750')
        self.page.get_by_role('spinbutton', name='To year').fill('1800')
        self.page.get_by_role('combobox').select_option(label='birth')
        self.page.get_by_role('searchbox', name='Search timeline').fill('Person')
        self.assertIn('from=1750', self.page.url); self.assertIn('to=1800', self.page.url); self.assertIn('kind=birth', self.page.url)
        self.page.reload(); self.assertEqual('1750', self.page.get_by_role('spinbutton', name='From year').input_value())
        self.page.get_by_role('button', name='Clear timeline filters').click()
        self.assertNotIn('from=', self.page.url); self.assertNotIn('kind=', self.page.url)
        self.assertIn('of 97 events shown', self.page.get_by_role('status').text_content())

    def test_signed_year_and_unknown_date_behavior(self):
        self.page.goto(self.base + 'timeline.html?from=-100&to=0')
        self.assertIn('excluded by the year filter', self.page.get_by_role('status').text_content())
        self.assertIn('-0044', self.page.locator('[data-timeline]').text_content())


if __name__ == '__main__':
    unittest.main()
