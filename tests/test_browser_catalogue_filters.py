"""Opt-in browser contract: the catalogue's research filters and the page address that keeps them."""
from __future__ import annotations

from functools import partial
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlsplit

from genealogy.case import CaseStore
from genealogy.config import ProjectConfig
from genealogy.models import AccessLevel as A, Claim, ClaimStatus, Confidence, Event, Relationship
from genealogy.site import build_site

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def demo_case():
    """The demo with fictional sex claims: two female, one male, one other value, and two that must not count."""
    config = ProjectConfig.load(ROOT / 'examples/demo/genealogy.toml')
    case = CaseStore(ROOT / 'examples/demo/cases').load(config.default_case)
    case.add_many([
        Claim('filter-sex-01', 'person:01', 'sex', 'F', sensitivity=A.PUBLIC),
        Claim('filter-sex-02', 'person:02', 'sex', 'Male', sensitivity=A.PUBLIC),
        Claim('filter-sex-03', 'person:03', 'sex', 'female', sensitivity=A.PUBLIC),
        Claim('filter-sex-04', 'person:04', 'sex', 'M', status=ClaimStatus.REJECTED, sensitivity=A.PUBLIC),
        Claim('filter-sex-05', 'person:05', 'sex', 'U', sensitivity=A.PUBLIC),
        Claim('filter-sex-06', 'person:06', 'sex', 'F', sensitivity=A.PRIVATE),
        # A disproved link records no parent and no child.
        Relationship('filter-disproved', 'person:13', 'person:02', 'parent', confidence=Confidence.DISPROVED, sensitivity=A.PUBLIC),
    ])
    return config, case


def large_case():
    from test_scale import large_case as base  # tests/ is on the path under unittest discovery
    case = base()
    records = []
    for n in range(0, 400):
        pid = f'p{n:04d}'
        if n % 4 < 2:
            records.append(Claim(f'{pid}-sex', pid, 'sex', 'F' if n % 4 == 0 else 'M', sensitivity=A.PUBLIC))
        if n % 10 == 0:
            records.append(Event(f'{pid}-d', 'death', date=str(1750 + n % 150), place_id=f'pl{n:04d}', participant_ids=[pid], sensitivity=A.PUBLIC))
        if n % 100 == 0:
            records.append(Relationship(f'{pid}-m', pid, f'p{n + 1:04d}', 'spouse', sensitivity=A.PUBLIC))
    case.add_many(records)
    return case


@unittest.skipUnless(os.environ.get('GENEALOGY_BROWSER_TESTS') == '1',
                     'Run make browser-check with the browser extra installed')
class CatalogueFilterBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        from test_scale import PEOPLE
        assert PEOPLE == 400, 'the large counts below assume 400 people'
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        config, case = demo_case()
        build_site(case, config, cls.root / 'demo')
        build_site(large_case(), ProjectConfig(name='Fictional large filters'), cls.root / 'large')
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

    @staticmethod
    def shown(text):
        """The result line as "matching of total": "Browsing all 42 people · …" or "16 matches of 42 people · …"."""
        found = re.match(r'Browsing all ([\d,]+) people|([\d,]+) match(?:es)? of ([\d,]+) people', text)
        return f'{found[1]} of {found[1]}' if found[1] else f'{found[2]} of {found[3]}'

    def count(self):
        return self.shown(self.page.locator('.result-count').inner_text())

    def filter(self, control, page=None):
        """A filter control, its filter group (a details pill) opened first."""
        group = (page or self.page).locator('details.filter-group', has=control)
        if not group.evaluate('d => d.open'):
            group.locator('summary').click()
        return control

    def label(self, text, page=None):
        return self.filter((page or self.page).get_by_label(text), page)

    def badges(self, page=None):
        """Each filter group's name and the number of its filters on, as its pill shows them."""
        return dict((page or self.page).locator('details.filter-group > summary').evaluate_all(
            "s => s.map(n => [n.firstChild.textContent, n.querySelector('.pill-count').textContent])"))

    def query(self):
        return {key: value[0] for key, value in parse_qs(urlsplit(self.page.url).query).items()}

    def open(self, site, query=''):
        self.page.goto(self.base + site + '/catalogue.html' + query, wait_until='networkidle')
        self.page.locator('.pagination').wait_for()

    def reset(self):
        self.page.get_by_role('button', name='Clear search and filters').click()

    def axe(self):
        if not os.environ.get('GENEALOGY_AXE_PATH'):
            return
        self.page.add_script_tag(content=Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8'))
        violations = self.page.evaluate(
            "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
            "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations.map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
        self.assertEqual([], violations)

    def test_each_filter_on_the_written_out_demo_catalogue(self):
        self.open('demo')
        page = self.page
        self.assertEqual('42 of 42', self.count())
        self.assertIn('Browsing all 42 people · 1–42 shown', page.locator('.result-count').inner_text())
        # The filters are grouped in pills, all closed, none on.
        self.assertEqual({'Name': '', 'Relatives': '', 'Dates': '', 'Places': '', 'Evidence': '', 'Filters': ''}, self.badges())
        self.assertEqual(0, page.locator('details.filter-group[open]').count())
        self.assertFalse(page.get_by_role('button', name='Clear search and filters').is_visible())
        sex = self.label('Recorded sex')
        self.axe()
        # The rejected claim and the private one count as not recorded.
        self.assertEqual(['Any', 'Female (2)', 'Male (1)', 'U (1)', 'Not recorded (38)'], sex.locator('option').all_inner_texts())
        for value, expected in (('F', '2'), ('M', '1'), ('U', '1'), ('not-recorded', '38')):
            sex.select_option(value)
            self.assertEqual(f'{expected} of 42', self.count(), value)
        sex.select_option('F')
        self.assertEqual({'person:01', 'person:03'}, set(page.locator('[data-person-id]:visible').evaluate_all('rows => rows.map(r => r.dataset.personId)')))
        self.assertEqual({'sex': 'F'}, self.query())
        self.assertEqual('1', self.badges()['Filters'])
        # Read out with the pill as "Filters (1 on)".
        self.assertEqual('Filters1 (1 on)', page.locator('details.filter-group > summary', has_text='Filters').text_content())
        self.reset()
        self.assertEqual('42 of 42', self.count())
        self.assertEqual({}, self.query())

        # Twelve people have no parent recorded (one with only a disproved link), sixteen have children, twenty-two no spouse.
        for label, expected in (('No parent recorded', '12'), ('Has recorded children', '16'), ('No recorded spouse or partner', '22')):
            box = self.label(label)
            box.check()
            self.assertEqual(f'{expected} of 42', self.count(), label)
            box.uncheck()
        self.label('No parent recorded').check()
        self.assertTrue(page.locator('[data-person-id="person:13"]').is_visible())
        self.label('Has recorded children').check()
        self.assertEqual('2', self.badges()['Relatives'])
        self.assertEqual('2 of 42', self.count())  # Ada Alder and Celia Bell; Bram Alder's only child link is disproved
        self.reset()

        self.label('Birth year from').fill('1810')
        self.label('Birth year to').fill('1816')
        self.assertEqual('16 of 42', self.count())
        self.assertIn('16 matches of 42 people · 1–16 shown', page.locator('.result-count').inner_text())
        self.reset()
        self.label('Death year from').fill('1899')
        self.assertEqual('6 of 42', self.count())
        self.label('Death year to').fill('1898')
        self.assertEqual('0 of 42', self.count())
        self.assertIn('0 matches of 42 people · none shown', page.locator('.result-count').inner_text())
        self.reset()
        # The place filter matches any event place, in part and without regard to case.
        self.label('Event place').fill('lantern')
        self.assertEqual('31 of 42', self.count())
        self.label('Birth year from').fill('1842')
        self.label('Birth year to').fill('1847')
        self.assertEqual('4 of 42', self.count())
        # The event-year range stays its own filter: no one born 1842-47 has an event in 1700-1750.
        self.label('Event year from').fill('1700')
        self.label('Event year to').fill('1750')
        self.assertEqual('0 of 42', self.count())
        self.assertEqual({'Name': '', 'Relatives': '', 'Dates': '4', 'Places': '1', 'Evidence': '', 'Filters': ''}, self.badges())
        self.assertEqual({'place': 'lantern', 'birth_from': '1842', 'birth_to': '1847', 'year_from': '1700', 'year_to': '1750'}, self.query())

    def test_the_page_address_keeps_every_filter(self):
        self.open('demo')
        page = self.page
        page.get_by_role('searchbox', name='Search people').fill('Cairn')
        # The menu: the Group row also has a checkbox labelled Surname.
        self.filter(page.get_by_label('Surname').and_(page.locator('select'))).select_option('Cairn')
        self.label('Recorded sex').select_option('not-recorded')
        self.label('Birth year from').fill('1784')
        self.label('Death year to').fill('1899')
        self.label('Event place').fill('Willowmere')
        self.label('No recorded spouse or partner').check()
        self.label('Evidence').select_option('unassessed')
        page.get_by_role('button', name='Birth', exact=True).click()
        shown = self.count()
        self.assertNotEqual('0 of 42', shown)
        address = page.url
        self.assertEqual({'q': 'Cairn', 'surname': 'Cairn', 'sex': 'not-recorded', 'birth_from': '1784', 'death_to': '1899',
                          'place': 'Willowmere', 'no_spouse': '1', 'evidence': 'unassessed', 'sort': 'birth'}, self.query())
        # Shared or reloaded, the address restores the same view, each group's pill counting its filters on.
        other = self.context.new_page()
        other.goto(address, wait_until='networkidle')
        other.locator('.pagination').wait_for()
        self.assertEqual(shown, self.shown(other.locator('.result-count').inner_text()))
        self.assertEqual({'Name': '1', 'Relatives': '1', 'Dates': '2', 'Places': '1', 'Evidence': '1', 'Filters': '1'}, self.badges(other))
        self.assertEqual('Cairn', other.get_by_role('searchbox', name='Search people').input_value())
        self.assertEqual('not-recorded', other.get_by_label('Recorded sex').input_value())
        self.assertEqual('1784', other.get_by_label('Birth year from').input_value())
        self.assertEqual('1899', other.get_by_label('Death year to').input_value())
        self.assertEqual('Willowmere', other.get_by_label('Event place').input_value())
        self.assertTrue(other.get_by_label('No recorded spouse or partner').is_checked())
        self.assertFalse(other.get_by_label('No parent recorded').is_checked())
        self.assertEqual('Birth ↑', other.locator('th[aria-sort="ascending"]').text_content())
        self.assertEqual(0, other.locator('th[aria-sort="descending"]').count())
        other.close()
        # Clearing keeps the sort and any parameter the catalogue does not own.
        self.open('demo', '?sort=death&from=elsewhere&birth_from=1810')
        self.assertEqual('22 of 42', self.count())
        self.reset()
        self.assertEqual({'sort': 'death', 'from': 'elsewhere'}, self.query())
        # An unknown value is ignored rather than filtering everyone out.
        self.open('demo', '?sex=X&surname=Nobody&no_parent=1')
        self.assertEqual('12 of 42', self.count())
        self.assertEqual('', self.page.get_by_label('Recorded sex').input_value())
        self.assertEqual('Individual ↑', self.page.locator('th[aria-sort="ascending"]').text_content())

    def test_each_filter_on_the_large_catalogue_built_from_the_data(self):
        self.open('large')
        page = self.page
        self.assertEqual('400 of 400', self.count())
        sex = self.label('Recorded sex')
        self.axe()
        self.assertEqual(['Any', 'Female (100)', 'Male (100)', 'Not recorded (200)'], sex.locator('option').all_inner_texts())
        sex.select_option('M')
        self.assertEqual('100 of 400', self.count())
        self.assertIn('Person 0001 Fable', page.locator('[data-person-id]:visible').first.inner_text())
        self.reset()
        for label, expected in (('No parent recorded', '1'), ('Has recorded children', '200'), ('No recorded spouse or partner', '392')):
            box = self.label(label)
            box.check()
            self.assertEqual(f'{expected} of 400', self.count(), label)
            box.uncheck()
        self.label('Birth year from').fill('1700')
        self.label('Birth year to').fill('1709')
        self.assertEqual('30 of 400', self.count())
        self.reset()
        self.label('Death year from').fill('1750')
        self.label('Death year to').fill('1759')
        self.assertEqual('3 of 400', self.count())  # p0000, p0150 and p0300
        self.reset()
        self.label('Event place').fill('Inventia')
        self.assertEqual('131 of 400', self.count())  # every third place, less two hamlets recorded without a country
        page.get_by_label('Event place').fill('hamlet')
        self.assertEqual('8 of 400', self.count())
        # Someone beyond the written-out first page is found and shown like the written rows.
        page.get_by_label('Event place').fill('Hamlet 0350')
        self.assertEqual('1 of 400', self.count())
        self.assertEqual(['1750', 'Hamlet 0350'], page.locator('[data-person-id="p0350"] td').all_inner_texts()[1:3])
        address = page.url
        self.assertEqual({'place': 'Hamlet 0350'}, self.query())
        self.page.goto(address, wait_until='networkidle')
        self.page.locator('.pagination').wait_for()
        self.assertEqual('1 of 400', self.count())
        # The surname and search parameters keep working alongside the new ones.
        # Person 0399 has no children; the search also finds their parent, who has.
        self.open('large', '?q=Person+0399&surname=Fable&has_children=1')
        self.assertEqual('1 of 400', self.count())
        self.assertTrue(self.page.locator('[data-person-id="p0199"]').is_visible())
        self.assertEqual('Fable', self.page.get_by_label('Surname').and_(self.page.locator('select')).input_value())


if __name__ == '__main__':
    unittest.main()
