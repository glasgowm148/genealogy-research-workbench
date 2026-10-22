"""Opt-in browser contract: the catalogue's research table, its sortable headings, grouping and map view."""
from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
import re
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlsplit

from genealogy.config import ProjectConfig
from genealogy.site import build_site

from test_catalogue_table import GRADES, HEADINGS, table_records  # tests/ is on the path under unittest discovery

ROWS = "[...document.querySelectorAll('tr[data-person-id]')].filter(r => !r.hidden)"


def year(text):
    found = re.search(r'\b(\d{4})\b', text)
    return int(found[1]) if found else None


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@unittest.skipUnless(os.environ.get('GENEALOGY_BROWSER_TESTS') == '1',
                     'Run make browser-check with the browser extra installed')
class CatalogueTableBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        from test_browser_catalogue_filters import demo_case
        from test_scale import large_case
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        config, case = demo_case()
        config.grades = GRADES
        case.add_many(table_records())
        build_site(case, config, cls.root / 'demo')
        cls.demo_people = len(case.records('Person')) - 1  # less the withheld parent
        large = large_case()
        large.add_many(table_records())
        build_site(large, ProjectConfig(name='Fictional large table', grades=GRADES), cls.root / 'large')
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

    def open(self, site, query=''):
        self.page.goto(self.base + site + '/catalogue.html' + query, wait_until='networkidle')
        self.page.locator('.result-count').wait_for()

    def query(self):
        return {key: value[0] for key, value in parse_qs(urlsplit(self.page.url).query).items()}

    def column(self, n):
        """The shown rows' text in column n (0 is Individual), in order."""
        return self.page.evaluate(f"{ROWS}.map(r => r.cells[{n}].textContent)")

    def heading(self, label):
        return self.page.get_by_role('button', name=label, exact=True)

    def sorted_by(self):
        return self.page.locator('th[aria-sort]').evaluate_all("t => t.map(n => [n.firstChild.firstChild.textContent, n.getAttribute('aria-sort')])")

    def axe(self):
        if not os.environ.get('GENEALOGY_AXE_PATH'):
            return
        self.page.add_script_tag(content=Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8'))
        violations = self.page.evaluate(
            "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
            "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations.map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
        self.assertEqual([], violations)

    def test_rows_built_from_the_data_match_the_written_rows(self):
        # A large site writes its first page; the script rebuilds the rows from the shared data, cell for cell the same.
        self.open('large')
        rows = "rows => rows.map(r => [r.dataset.personId, r.dataset.surname, r.innerHTML])"
        written = self.page.evaluate("async () => { const doc = new DOMParser().parseFromString(await (await fetch('catalogue.html')).text(), 'text/html');"
                                     f" return ({rows})([...doc.querySelectorAll('tr[data-person-id]')]); }}")
        live = self.page.evaluate(f"({rows})({ROWS})")
        self.assertEqual(50, len(written))
        self.assertEqual(written, live)
        ada = self.page.locator('[data-person-id="t0001"]')
        self.assertIn('Strongly supported (80%)', ada.locator('td').nth(7).inner_text())
        self.assertEqual(['date-approx', 'date-exact'], [ada.locator('td').nth(n).get_attribute('class') for n in (1, 3)])
        # A row past the first page has the same eight columns.
        self.page.get_by_role('searchbox', name='Search people').fill('Person 0399')
        row = self.page.locator('[data-person-id="p0399"]')
        self.assertEqual(['1799', 'Town 0399, Shire 0, Fableland', '—', '—', '—', 'Person 0199 FableParent ○Unassessed tree link', '—'],  # no recorded sex: "Parent" under Father
                         [t.strip() for t in row.locator('td').all_text_contents()[1:]])
        self.assertEqual('p0399', row.locator('.record-id').inner_text())

    def test_the_column_headings_sort_and_keep_the_address(self):
        self.open('demo')
        page = self.page
        self.assertEqual(HEADINGS, [h.strip(' ↑↓↕') for h in page.locator('thead th').all_text_contents()])
        self.assertEqual([['Individual', 'ascending']], self.sorted_by())
        names = self.column(0)
        self.heading('Birth').click()
        self.assertEqual([['Birth', 'ascending']], self.sorted_by())
        self.assertEqual({'sort': 'birth'}, self.query())
        years = [year(t) for t in self.column(1)]
        known = [y for y in years if y is not None]
        self.assertEqual(sorted(known), known)
        # People without a recorded birth come last either way.
        self.assertEqual([None] * (len(years) - len(known)), years[len(known):])
        self.heading('Birth').click()
        self.assertEqual([['Birth', 'descending']], self.sorted_by())
        self.assertEqual({'sort': 'birth-desc'}, self.query())
        years = [year(t) for t in self.column(1) if year(t)]
        self.assertEqual(sorted(years, reverse=True), years)
        self.assertEqual('—', self.column(1)[-1])
        # Enter on a heading sorts too.
        self.heading('Death').focus()
        page.keyboard.press('Enter')
        self.assertEqual([['Death', 'ascending']], self.sorted_by())
        self.assertEqual({'sort': 'death'}, self.query())
        # Relatives sort by the first relative's surname.
        self.heading('Mother').click()
        mothers = [t.split(' ')[1] for t in self.column(7) if t != '—']
        self.assertEqual(sorted(mothers), mothers)
        self.assertEqual('—', self.column(7)[-1])
        self.heading('Individual').click()
        self.assertEqual(names, self.column(0))
        self.assertEqual({}, self.query())
        # The address restores a heading's sort, and the filters still apply under it.
        self.open('demo', '?sort=father-desc&q=Table')
        self.assertEqual([['Father', 'descending']], self.sorted_by())
        self.assertEqual('Ada Table', self.column(0)[0].removesuffix('Table-12'))

    def test_grouping_by_birth_region_and_surname(self):
        self.open('demo')
        page = self.page
        page.get_by_role('checkbox', name='Location').check()
        self.assertEqual({'group_location': '1'}, self.query())
        groups = page.locator('tbody tr.group th')
        headings = groups.all_text_contents()
        self.assertIn('Fableland · 1 person', headings)
        self.assertEqual('No birth place recorded', headings[-1].split(' · ')[0])
        # Each person sits under the last part of their birth place.
        under = page.evaluate("[...document.querySelectorAll('tbody tr')].filter(r => !r.hidden).reduce((a, r) => { if (r.classList.contains('group')) a.group = r.textContent.split(' · ')[0];"
                              " else a.rows.push([a.group, r.cells[2].textContent]); return a; }, {rows: []}).rows")
        for group, place in under:
            self.assertEqual(group, place.split(',')[-1].strip() if place != '—' else 'No birth place recorded', place)
        page.get_by_role('checkbox', name='Surname').check()
        self.assertIn('Fableland · Table · 1 person', groups.all_text_contents())
        page.get_by_role('checkbox', name='Location').uncheck()
        self.assertIn('Table · 4 people', groups.all_text_contents())  # Ada, Bram, Dov and Hugo; the withheld parent is not counted
        self.assertEqual({'group_surname': '1'}, self.query())
        page.get_by_role('checkbox', name='Surname').uncheck()
        self.assertEqual(0, groups.count())
        # On a large site a group that runs on past a page starts the next page with its heading.
        self.open('large', '?group_surname=1')
        self.assertEqual(['Fable · 400 people'], groups.all_text_contents())
        page.get_by_role('button', name='Next').click()
        self.assertEqual(['Fable · 400 people'], groups.all_text_contents())
        self.assertEqual(51, page.locator('tbody tr').count())
        self.assertTrue(page.get_by_role('button', name='Clear search and filters').is_hidden())  # grouping is not a filter
        self.assertTrue(page.get_by_role('checkbox', name='Surname').is_checked())

    def test_the_map_shows_the_matching_peoples_birth_places(self):
        self.open('demo')
        page = self.page
        table, view = page.locator('[data-catalogue]'), page.locator('.catalogue-map')
        self.assertFalse(view.is_visible())
        page.get_by_role('button', name='Map', exact=True).click()
        self.assertEqual('true', page.get_by_role('button', name='Map', exact=True).get_attribute('aria-pressed'))
        self.assertFalse(table.is_visible())
        self.assertFalse(page.locator('.pagination').is_visible())
        self.assertEqual({'view': 'map'}, self.query())
        markers = view.locator('.catalogue-map-marker')
        self.assertGreater(markers.count(), 1)
        # Every marker's count adds up to the people the note says have a located birth place, and the list says the same.
        counts = [int(t.rsplit(': ', 1)[1].split(' ')[0]) for t in markers.locator('title').all_text_contents()]
        located = int(view.locator('p.hint').inner_text().split(' of ')[0])
        self.assertEqual(located, sum(counts))
        listed = [int(t.split(' · ')[1].split(' ')[0]) for t in view.locator('ol.catalogue-map-list > li').all_inner_texts()]
        self.assertEqual(located, sum(listed))
        self.axe()
        # The search narrows the map like the table.
        page.get_by_role('searchbox', name='Search people').fill('Ada Table')
        self.assertEqual(['Lanternby, North Shire, Fableland: 1 person'], markers.locator('title').all_text_contents())
        self.assertIn('Ada Table', view.locator('ol.catalogue-map-list').inner_text())
        self.assertTrue(view.get_by_role('link', name='Ada Table').get_attribute('href').startswith('people/p-'))
        address = page.url
        page.goto(address, wait_until='networkidle')
        self.assertTrue(view.is_visible())
        self.assertEqual(['Lanternby, North Shire, Fableland: 1 person'], markers.locator('title').all_text_contents())
        page.get_by_role('button', name='Table', exact=True).click()
        self.assertTrue(table.is_visible())
        self.assertEqual({'q': 'Ada Table'}, self.query())
        # A large site maps everyone matching, not just one page.
        self.open('large', '?view=map&place=Inventia')
        # Every third place is in Inventia, less two hamlets recorded without a country; and Ada Table died there.
        self.assertIn('of 132 matching people have a birth place', view.locator('p.hint').inner_text())

    def test_wcag_aa_and_layout_at_both_widths(self):
        for site in ('demo', 'large'):
            for width in (1440, 390):
                with self.subTest(site=site, width=width):
                    self.page.set_viewport_size({'width': width, 'height': 900})
                    self.open(site, '?group_location=1&birth_from=1700')
                    self.page.locator('details.filter-group > summary', has_text='Dates').click()
                    self.assertTrue(self.page.get_by_label('Birth year to').is_visible())
                    self.axe()
                    self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1)
                    if width == 390:
                        # The table scrolls inside its frame, and the pills wrap onto more than one line.
                        self.assertGreater(*self.page.locator('.table-wrap').evaluate('w => [w.scrollWidth, w.clientWidth]'))
                        tops = self.page.locator('details.filter-group > summary').evaluate_all('s => s.map(n => n.getBoundingClientRect().top)')
                        self.assertGreater(len(set(tops)), 1)
                    self.page.get_by_role('button', name='Map', exact=True).click()
                    self.axe()
                    self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1)

    def test_without_javascript_the_table_reads_in_full(self):
        context = self.browser.new_context(java_script_enabled=False)
        try:
            page = context.new_page()
            page.goto(self.base + 'demo/catalogue.html')
            self.assertEqual(HEADINGS, page.locator('thead th').all_text_contents())
            rows = page.locator('tr[data-person-id]')
            self.assertEqual(self.demo_people, rows.count())
            self.assertEqual({8}, set(page.evaluate("[...document.querySelectorAll('tr[data-person-id]')].map(r => r.cells.length)")))
            ada = page.locator('[data-person-id="t0001"]')
            self.assertIn('Gwen Vale', ada.inner_text())
            self.assertEqual(1, ada.locator('a.evidence-badge[href="evidence.html#grade-strongly_supported"]').count())
        finally:
            context.close()
        for path in self.root.rglob('*'):
            if path.is_file():
                self.assertNotIn('SECRET-PARENT', path.read_text(encoding='utf-8', errors='ignore'), path)


if __name__ == '__main__':
    unittest.main()
