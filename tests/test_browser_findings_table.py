"""Opt-in browser contract: the findings table's filters, the address that keeps them, the card layout and axe."""
from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlsplit

from genealogy.site import build_site
from genealogy.config import ProjectConfig


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@unittest.skipUnless(os.environ.get('GENEALOGY_BROWSER_TESTS') == '1',
                     'Run make browser-check with the browser extra installed')
class FindingsTableBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        from test_findings_table import case  # tests/ is on the path under unittest discovery
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        # 43 public findings: the page shows the newest 30 and the undated one, the index holds all.
        build_site(case(many=40), ProjectConfig(name='Fictional findings', raw={'site': {'base_url': 'https://example.invalid/'}}), cls.root / 'log')
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(cls.root)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}/log/'
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

    def open(self, route='findings.html', query=''):
        self.page.goto(self.base + route + query, wait_until='networkidle')
        self.page.locator('.findings-filters').wait_for()

    def status(self):
        return self.page.locator('.findings-match').inner_text()

    def shown(self):
        return self.page.locator('tr.finding-entry:visible').evaluate_all('rows => rows.map(r => r.dataset.findingId)')

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

    def test_filters_search_every_finding_through_the_index(self):
        self.open()
        page = self.page
        page.wait_for_function('Array.isArray(window.GENEALOGY_FINDINGS)')
        self.assertEqual(31, len(self.shown()))
        self.assertEqual('', self.status())
        self.assertFalse(page.get_by_role('button', name='Reset').is_visible())
        self.axe()
        # Option labels and counts cover all 43 findings; the names come from the shared data.
        self.assertEqual(['Everyone', 'Ada Fable (22)', 'Bram Fable (22)'], page.get_by_label('Person').locator('option').all_inner_texts())
        self.assertEqual(['All types', 'Record (41)', 'Vital (1)'], page.get_by_label('Finding type').locator('option').all_inner_texts())
        page.get_by_label('Finding type').select_option('vital')
        self.assertEqual('1 of 43 findings match.', self.status())
        self.assertEqual(['f-baptism'], self.shown())
        self.assertFalse(page.locator('tr.findings-month').first.is_visible())
        self.assertEqual({'kind': 'vital'}, self.query())
        page.get_by_role('button', name='Reset').click()
        self.assertEqual(31, len(self.shown()))
        self.assertTrue(page.locator('tr.findings-month').first.is_visible())
        self.assertEqual({}, self.query())
        # A person's findings include those older than the page holds, built from the index.
        page.get_by_label('Person').select_option('bram')
        self.assertEqual('22 of 43 findings match.', self.status())
        ids = self.shown()
        self.assertEqual(22, len(ids))
        self.assertIn('f001', ids)  # on an archive page, not this one
        older = page.locator('tr.finding-entry[data-finding-id="f001"]')
        self.assertEqual('Numbered conclusion 1.', older.locator('.finding-conclusion').inner_text())
        self.assertTrue(older.locator('a', has_text='Numbered conclusion 1.').get_attribute('href').startswith('research.html#'))
        self.assertEqual('Bram Fable', older.locator('td[data-label="People"]').inner_text())
        self.axe()
        # Words, order and status together; the address keeps them all.
        page.get_by_label('Person').select_option('')
        page.get_by_role('searchbox', name='Search findings').fill('NUMBERED conclusion')
        self.assertEqual('40 of 43 findings match.', self.status())
        page.get_by_label('Order').select_option('oldest')
        self.assertEqual('f000', self.shown()[0])
        page.get_by_label('Status').select_option('final')
        self.assertEqual({'q': 'NUMBERED conclusion', 'order': 'oldest', 'status': 'final'}, self.query())
        page.get_by_role('searchbox', name='Search findings').fill('Lanternford')  # a place's name finds its findings
        self.assertEqual('0 of 43 findings match.', self.status())
        page.get_by_label('Status').select_option('')
        self.assertEqual(['f-baptism'], self.shown())
        page.get_by_role('searchbox', name='Search findings').fill('no such words')
        self.assertEqual('0 of 43 findings match.', self.status())
        self.assertTrue(page.get_by_text('No findings match these filters.').is_visible())

    def test_study_and_place_links_open_a_filtered_view(self):
        self.open()
        link = self.page.locator('#by-study ~ ul a', has_text='The Fable household')
        link.click()
        self.page.wait_for_load_state('networkidle')
        self.page.wait_for_function("document.querySelector('.findings-match').textContent.includes('of 43')")
        self.assertEqual('household', self.page.get_by_label('Family or place study').input_value())
        self.assertEqual('22 of 43 findings match.', self.status())
        self.open(query='?place=willow')
        self.page.wait_for_function("document.querySelector('.findings-match').textContent.includes('of 43')")
        self.assertEqual(['f-brother'], self.shown())
        self.assertEqual('Willowmere (fictional) (1)', self.page.get_by_role('combobox', name='Place', exact=True).locator('option:checked').inner_text())

    def test_an_archive_page_filters_its_own_rows(self):
        self.open('findings/page-1.html')
        page = self.page
        self.assertEqual(['Everyone', 'Ada Fable (21)', 'Bram Fable (21)'], page.get_by_label('Person').locator('option').all_inner_texts())
        page.get_by_label('Person').select_option('ada')
        self.assertEqual('21 of 42 findings on this page match.', self.status())
        self.axe()

    def test_narrow_screens_get_labelled_cards(self):
        self.context.close()
        self.context = self.browser.new_context(viewport={'width': 390, 'height': 900})
        self.page = self.context.new_page()
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))
        self.open()
        page = self.page
        self.assertFalse(page.locator('.findings-table thead').is_visible() and page.locator('.findings-table thead').bounding_box()['height'] > 2)
        self.assertEqual('"Finding"', page.locator('tr.finding-entry td[data-label="Finding"]').first.evaluate("td => getComputedStyle(td, '::before').content"))
        self.assertEqual('block', page.locator('tr.finding-entry').first.evaluate('tr => getComputedStyle(tr).display'))
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
        self.axe()

    def test_without_javascript_the_table_is_all_there(self):
        context = self.browser.new_context(java_script_enabled=False)
        page = context.new_page()
        page.goto(self.base + 'findings.html')
        self.assertEqual(31, page.locator('tr.finding-entry').count())
        self.assertEqual(0, page.locator('.findings-filters').count())
        self.assertTrue(page.get_by_role('link', name='Follow new findings (Atom feed)').is_visible())
        self.assertTrue(page.get_by_role('columnheader', name='Status and kind').is_visible())
        context.close()


if __name__ == '__main__':
    unittest.main()
