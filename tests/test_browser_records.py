"""Opt-in browser contract: the records page searches, filters, sorts and pages every citation, and keeps its filters in the address."""
from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlsplit

from genealogy.config import ProjectConfig
from genealogy.site import build_site


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@unittest.skipUnless(os.environ.get('GENEALOGY_BROWSER_TESTS') == '1',
                     'Run make browser-check with the browser extra installed')
class RecordsBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        from test_records_page import CONFIG, case
        from test_scale import large_case
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        build_site(case(), CONFIG, cls.root / 'small')
        build_site(large_case(), ProjectConfig(name='Fictional large records'), cls.root / 'large')
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
        self.context = self.browser.new_context(viewport={'width': 1280, 'height': 1000})
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))

    def tearDown(self):
        self.context.close()
        self.assertEqual([], self.errors, 'Browser runtime errors')

    def open(self, site, query=''):
        self.page.goto(self.base + site + '/records.html' + query, wait_until='networkidle')
        self.page.locator('[data-records-count]').wait_for()

    def count(self):
        return self.page.locator('[data-records-count]').inner_text()

    def years(self):
        return self.page.locator('.records-table tbody td[data-label="Year"]').all_inner_texts()

    def query(self):
        return {key: value[0] for key, value in parse_qs(urlsplit(self.page.url).query).items()}

    def axe(self):
        if not os.environ.get('GENEALOGY_AXE_PATH'):
            return
        self.page.add_script_tag(content=Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8'))
        violations = self.page.evaluate(
            "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
            "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations.map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
        self.assertEqual([], violations)

    def test_filters_sort_and_the_address(self):
        self.open('small')
        self.assertEqual('1–5 of 5 cited records', self.count())
        self.assertEqual(['1801', '1822', '1841', 'Undated', 'Undated'], self.years())
        self.assertTrue(self.page.locator('.records-filters').is_visible())
        self.assertFalse(self.page.locator('[data-records-static]').is_visible())
        # The script draws the same row as the page: links, badge and the abstract's line.
        first = self.page.locator('.records-table tbody tr').first
        self.assertEqual('Ada Fable', first.locator('td[data-label="People"] a').inner_text())
        self.assertEqual('evidence.html#confidence-documented', first.locator('.evidence-badge').get_attribute('href'))
        self.assertEqual('Invented parish register (entry 75)', first.locator('td[data-label="Details"] a').inner_text())
        self.assertTrue(first.locator('.records-abstract').inner_text().endswith('…'))
        self.assertIn('+1 more', self.page.locator('.records-table tbody tr').nth(2).inner_text())
        self.page.locator('select[name=type]').select_option('census')
        self.assertEqual('1–3 of 3 matching records (of 5)', self.count())
        self.page.locator('input[name=year_from]').fill('1820')
        self.assertEqual(['1841'], self.years())
        self.assertEqual({'type': 'census', 'year_from': '1820'}, self.query())
        self.page.get_by_role('button', name='Clear filters').click()
        self.assertEqual('1–5 of 5 cited records', self.count())
        self.assertEqual({}, self.query())
        self.page.locator('select[name=evidence]').select_option('unassessed')
        self.assertEqual(['1822', 'Undated'], self.years())
        self.page.locator('select[name=evidence]').select_option('')
        self.page.locator('.records-filters input[name=q]').fill('bram household')
        self.assertEqual(['1841'], self.years())
        self.page.locator('.records-filters input[name=q]').fill('zzz-nothing')
        self.assertIn('No records match these filters', self.count())
        self.assertFalse(self.page.locator('.records-table').is_visible())
        # A shared address opens the same view; newest first keeps undated records last.
        self.open('small', '?sort=year-desc&evidence=assessed')
        self.assertEqual(['1841', '1801', 'Undated'], self.years())
        self.page.locator('select[data-records-sort]').select_option('person')
        self.assertEqual('Ada Fable', self.page.locator('.records-table tbody tr').first.locator('td[data-label="People"] a').first.inner_text())
        self.assertEqual({'sort': 'person', 'evidence': 'assessed'}, self.query())
        self.axe()

    def test_a_large_site_searches_and_pages_every_record(self):
        self.open('large')
        self.assertEqual('1–50 of 401 cited records', self.count())
        self.assertFalse(self.page.locator('[data-records-pages]').is_visible())
        self.assertEqual(50, self.page.locator('.records-table tbody tr').count())
        self.page.get_by_role('button', name='Next →').click()
        self.assertEqual('51–100 of 401 cited records', self.count())
        self.page.locator('.records-filters input[name=q]').fill('Person 0390')
        # The shared record also cites this person, beyond its first three displayed names.
        self.assertEqual('1–2 of 2 matching records (of 401)', self.count())
        self.assertIn('Invented register volume 0390 (folio 390)', self.page.locator('.records-table tbody').inner_text())
        self.assertFalse(self.page.locator('.records-table + .pagination, [data-records] + .pagination').is_visible())
        self.axe()

    def test_phone_width_and_no_javascript(self):
        for site in ('small', 'large'):
            self.page.set_viewport_size({'width': 390, 'height': 900})
            self.open(site)
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 391, site)
            self.axe()
        nojs = self.browser.new_context(java_script_enabled=False)
        try:
            page = nojs.new_page()
            page.goto(self.base + 'large/records.html')
            self.assertEqual(100, page.locator('.records-table tbody tr').count())
            self.assertFalse(page.locator('.records-filters').is_visible())
            self.assertTrue(page.locator('[data-records-pages]').is_visible())
            page.locator('[data-records-pages] a').nth(1).click()
            self.assertIn('records/page-2.html', page.url)
            self.assertEqual(100, page.locator('.records-table tbody tr').count())
        finally:
            nojs.close()


if __name__ == '__main__':
    unittest.main()
