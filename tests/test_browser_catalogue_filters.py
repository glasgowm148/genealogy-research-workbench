"""Opt-in browser contract: the catalogue's research filters and the page address that keeps them."""
from __future__ import annotations

from functools import partial
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

    def count(self):
        return self.page.locator('.result-count').inner_text().split(' people')[0]

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
        panel = page.locator('details.catalogue-filters')
        self.assertFalse(panel.evaluate('d => d.open'))
        self.assertFalse(page.get_by_role('button', name='Clear search and filters').is_visible())
        panel.locator('summary').click()
        self.axe()
        sex = page.get_by_label('Recorded sex')
        # The rejected claim and the private one count as not recorded.
        self.assertEqual(['Any', 'Female (2)', 'Male (1)', 'U (1)', 'Not recorded (38)'], sex.locator('option').all_inner_texts())
        for value, expected in (('F', '2'), ('M', '1'), ('U', '1'), ('not-recorded', '38')):
            sex.select_option(value)
            self.assertEqual(f'{expected} of 42', self.count(), value)
        sex.select_option('F')
        self.assertEqual({'person:01', 'person:03'}, set(page.locator('[data-person-id]:visible').evaluate_all('rows => rows.map(r => r.dataset.personId)')))
        self.assertEqual({'sex': 'F'}, self.query())
        self.assertIn('Research filters · 1 on', panel.locator('summary').inner_text())
        self.reset()
        self.assertEqual('42 of 42', self.count())
        self.assertEqual({}, self.query())

        # Twelve people have no parent recorded (one with only a disproved link), sixteen have children, twenty-two no spouse.
        for label, expected in (('No parent recorded', '12'), ('Has recorded children', '16'), ('No recorded spouse or partner', '22')):
            box = page.get_by_label(label)
            box.check()
            self.assertEqual(f'{expected} of 42', self.count(), label)
            box.uncheck()
        page.get_by_label('No parent recorded').check()
        self.assertTrue(page.locator('[data-person-id="person:13"]').is_visible())
        page.get_by_label('Has recorded children').check()
        self.assertEqual('2 of 42', self.count())  # Ada Alder and Celia Bell; Bram Alder's only child link is disproved
        self.reset()

        page.get_by_label('Birth year from').fill('1810')
        page.get_by_label('Birth year to').fill('1816')
        self.assertEqual('16 of 42', self.count())
        self.reset()
        page.get_by_label('Death year from').fill('1899')
        self.assertEqual('6 of 42', self.count())
        page.get_by_label('Death year to').fill('1898')
        self.assertEqual('0 of 42', self.count())
        self.reset()
        # The place filter matches any event place, in part and without regard to case.
        page.get_by_label('Event place').fill('lantern')
        self.assertEqual('31 of 42', self.count())
        page.get_by_label('Birth year from').fill('1842')
        page.get_by_label('Birth year to').fill('1847')
        self.assertEqual('4 of 42', self.count())
        # The event-year range stays its own filter: no one born 1842-47 has an event in 1700-1750.
        page.get_by_label('Event year from').fill('1700')
        page.get_by_label('Event year to').fill('1750')
        self.assertEqual('0 of 42', self.count())
        self.assertEqual({'place': 'lantern', 'birth_from': '1842', 'birth_to': '1847', 'year_from': '1700', 'year_to': '1750'}, self.query())

    def test_the_page_address_keeps_every_filter(self):
        self.open('demo')
        page = self.page
        page.get_by_role('searchbox', name='Search people').fill('Cairn')
        page.get_by_label('Surname').select_option('Cairn')
        page.locator('details.catalogue-filters summary').click()
        page.get_by_label('Recorded sex').select_option('not-recorded')
        page.get_by_label('Birth year from').fill('1784')
        page.get_by_label('Death year to').fill('1899')
        page.get_by_label('Event place').fill('Willowmere')
        page.get_by_label('No recorded spouse or partner').check()
        page.get_by_label('Evidence').select_option('unassessed')
        page.get_by_label('Sort by').select_option('birth')
        shown = self.count()
        self.assertNotEqual('0 of 42', shown)
        address = page.url
        self.assertEqual({'q': 'Cairn', 'surname': 'Cairn', 'sex': 'not-recorded', 'birth_from': '1784', 'death_to': '1899',
                          'place': 'Willowmere', 'no_spouse': '1', 'evidence': 'unassessed', 'sort': 'birth'}, self.query())
        # Shared or reloaded, the address restores the same view with the filters open.
        other = self.context.new_page()
        other.goto(address, wait_until='networkidle')
        other.locator('.pagination').wait_for()
        self.assertEqual(shown, other.locator('.result-count').inner_text().split(' people')[0])
        self.assertTrue(other.locator('details.catalogue-filters').evaluate('d => d.open'))
        self.assertEqual('Cairn', other.get_by_role('searchbox', name='Search people').input_value())
        self.assertEqual('not-recorded', other.get_by_label('Recorded sex').input_value())
        self.assertEqual('1784', other.get_by_label('Birth year from').input_value())
        self.assertEqual('1899', other.get_by_label('Death year to').input_value())
        self.assertEqual('Willowmere', other.get_by_label('Event place').input_value())
        self.assertTrue(other.get_by_label('No recorded spouse or partner').is_checked())
        self.assertFalse(other.get_by_label('No parent recorded').is_checked())
        self.assertEqual('birth', other.get_by_label('Sort by').input_value())
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

    def test_each_filter_on_the_large_catalogue_built_from_the_data(self):
        self.open('large')
        page = self.page
        self.assertEqual('400 of 400', self.count())
        page.locator('details.catalogue-filters summary').click()
        self.axe()
        sex = page.get_by_label('Recorded sex')
        self.assertEqual(['Any', 'Female (100)', 'Male (100)', 'Not recorded (200)'], sex.locator('option').all_inner_texts())
        sex.select_option('M')
        self.assertEqual('100 of 400', self.count())
        self.assertIn('Person 0001 Fable', page.locator('[data-person-id]:visible').first.inner_text())
        self.reset()
        for label, expected in (('No parent recorded', '1'), ('Has recorded children', '200'), ('No recorded spouse or partner', '392')):
            box = page.get_by_label(label)
            box.check()
            self.assertEqual(f'{expected} of 400', self.count(), label)
            box.uncheck()
        page.get_by_label('Birth year from').fill('1700')
        page.get_by_label('Birth year to').fill('1709')
        self.assertEqual('30 of 400', self.count())
        self.reset()
        page.get_by_label('Death year from').fill('1750')
        page.get_by_label('Death year to').fill('1759')
        self.assertEqual('3 of 400', self.count())  # p0000, p0150 and p0300
        self.reset()
        page.get_by_label('Event place').fill('Inventia')
        self.assertEqual('131 of 400', self.count())  # every third place, less two hamlets recorded without a country
        page.get_by_label('Event place').fill('hamlet')
        self.assertEqual('8 of 400', self.count())
        # Someone beyond the written-out first page is found and shown like the written rows.
        page.get_by_label('Event place').fill('Hamlet 0350')
        self.assertEqual('1 of 400', self.count())
        self.assertIn('b. 1750', page.locator('[data-person-id="p0350"]').inner_text())
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
        self.assertEqual('Fable', self.page.get_by_label('Surname').input_value())


if __name__ == '__main__':
    unittest.main()
