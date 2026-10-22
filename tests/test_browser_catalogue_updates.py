"""Opt-in browser contract: update priority in the catalogue — the line and chips under a name, the update sorts, the Table / Map tabs."""
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

from test_catalogue_find_person import config  # tests/ is on the path under unittest discovery
from test_catalogue_updates import update_case, update_records

ROWS = "[...document.querySelectorAll('tr[data-person-id]')].filter(r => !r.hidden)"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@unittest.skipUnless(os.environ.get('GENEALOGY_BROWSER_TESTS') == '1',
                     'Run make browser-check with the browser extra installed')
class CatalogueUpdatesBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        from test_scale import large_case
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        build_site(update_case(), config(), cls.root / 'updates')
        large = large_case()
        large.add_many(update_records())
        build_site(large, config(), cls.root / 'large')
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
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))

    def tearDown(self):
        self.context.close()
        self.assertEqual([], self.errors, 'Browser runtime errors')

    def open(self, query='', site='updates'):
        self.page.goto(self.base + site + '/catalogue.html' + query, wait_until='networkidle')
        self.page.locator('.pagination').wait_for()

    def ids(self):
        return self.page.evaluate(f"{ROWS}.map(r => r.dataset.personId)")

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

    def test_rows_built_from_the_data_match_the_written_rows(self):
        # A large site writes its first page (Ada to Jory come before "Person 0000"); the script rebuilds every row, line and chips included.
        self.open(site='large')
        rows = "rows => rows.map(r => [r.dataset.personId, r.innerHTML])"
        written = self.page.evaluate("async () => { const doc = new DOMParser().parseFromString(await (await fetch('catalogue.html')).text(), 'text/html');"
                                     f" return ({rows})([...doc.querySelectorAll('tr[data-person-id]')]); }}")
        live = self.page.evaluate(f"({rows})({ROWS})")
        self.assertEqual(written, live)
        ada = self.page.locator('[data-person-id="f01"] td').first
        self.assertEqual('Needs updated on FableTree · significance 55', ada.locator('.update-line').inner_text())
        self.assertEqual(['father added', 'spouse now Strongly supported 90%'], [t.strip('✓~?○✕ ') for t in ada.locator('.update-chip').all_inner_texts()])
        self.assertEqual(6, sum('update-line' in html for _, html in written))

    def test_the_update_sorts(self):
        self.open()
        sort = self.page.get_by_label('Sort results')
        for value, expected in (
                # Pending father changes first (Jory 70, Ada 55, Finn none), then other pending changes (Dov 70, Bram 55, Hugo none), then name order.
                ('priority', ['f10', 'f01', 'f06', 'f04', 'f02', 'f08', 'f03', 'f05', 'f07', 'f09']),
                ('significance', ['f04', 'f10', 'f01', 'f02', 'f03', 'f05', 'f06', 'f07', 'f08', 'f09']),
                # Ada's new father is documented, Finn's probable, Jory's possible (his disproved one ranks lower); the rest by name.
                ('father-changes', ['f01', 'f06', 'f10', 'f02', 'f03', 'f04', 'f05', 'f07', 'f08', 'f09'])):
            sort.select_option(value)
            self.assertEqual(expected, self.ids(), value)
            self.assertEqual({'sort': value}, self.query())
            self.page.reload(wait_until='networkidle')
            self.assertEqual(value, sort.input_value())
            self.assertEqual(expected, self.ids(), value)
        # After Best match, which is offered with a query.
        self.page.get_by_role('searchbox', name='Search people').fill('fable')
        labels = sort.locator('option').evaluate_all('o => o.filter(n => !n.hidden).map(n => n.textContent)')
        self.assertEqual(['Best match', 'Update priority: new fathers first', 'Update significance', 'Father changes: highest confidence', 'Name A–Z'], labels[:5])

    def test_table_and_map_are_tabs(self):
        for width in (1440, 390):
            with self.subTest(width=width):
                self.page.set_viewport_size({'width': width, 'height': 900})
                self.open()
                page = self.page
                tabs = page.get_by_role('tablist', name='Show the people as').get_by_role('tab')
                self.assertEqual(['Table', 'Map'], tabs.all_inner_texts())
                table, map_tab = page.get_by_role('tab', name='Table', exact=True), page.get_by_role('tab', name='Map', exact=True)
                self.assertEqual(['true', 'false'], [table.get_attribute('aria-selected'), map_tab.get_attribute('aria-selected')])
                self.assertEqual(['0', '-1'], [table.get_attribute('tabindex'), map_tab.get_attribute('tabindex')])
                self.assertEqual('tabpanel', page.locator(f'#{table.get_attribute("aria-controls")}').get_attribute('role'))
                self.axe()
                table.focus()
                page.keyboard.press('ArrowRight')
                self.assertEqual('true', map_tab.get_attribute('aria-selected'))
                self.assertTrue(map_tab.evaluate('t => t === document.activeElement'))
                self.assertTrue(page.locator('.catalogue-map').is_visible())
                self.assertFalse(page.locator('[data-catalogue]').is_visible())
                self.assertEqual({'view': 'map'}, self.query())
                self.axe()
                page.keyboard.press('Home')
                self.assertEqual('true', table.get_attribute('aria-selected'))
                self.assertTrue(page.locator('[data-catalogue]').is_visible())
                page.keyboard.press('ArrowLeft')  # wraps round to the last tab
                self.assertEqual('true', map_tab.get_attribute('aria-selected'))
                page.keyboard.press('End')
                self.assertEqual('true', map_tab.get_attribute('aria-selected'))
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width + 1)

    def test_without_javascript_the_line_and_chips_are_written(self):
        context = self.browser.new_context(java_script_enabled=False)
        try:
            page = context.new_page()
            page.goto(self.base + 'updates/catalogue.html')
            ada = page.locator('[data-person-id="f01"] td').first
            self.assertEqual('Needs updated on FableTree · significance 55', ada.locator('.update-line').inner_text())
            self.assertEqual(2, ada.locator('a.update-chip').count())
            self.assertEqual(0, page.locator('[data-person-id="f07"] .update-line').count())
        finally:
            context.close()


if __name__ == '__main__':
    unittest.main()
