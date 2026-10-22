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
        """A filter control, its menu (a details pill) opened first."""
        group = (page or self.page).locator('details.filter-group', has=control)
        if not group.evaluate('d => d.open'):
            group.locator('summary').click()
        return control

    def label(self, text, page=None, exact=False):
        """A control in the menus, by its label, its menu opened first (the result toolbar also has a Location box)."""
        page = page or self.page
        group = page.locator('details.filter-group', has=page.get_by_label(text, exact=exact))
        if not group.evaluate('d => d.open'):
            group.locator('summary').click()
        return group.get_by_label(text, exact=exact)

    def gender(self, label, page=None):
        """A Gender radio, its menu opened first (a closed menu's radios have no role to find them by)."""
        self.filter((page or self.page).locator('input[name="sex"]').first, page)
        return (page or self.page).get_by_role('radio', name=label, exact=True)

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
        # The filters are grouped in the seven menus, all closed, none on.
        self.assertEqual({'Name': '', 'Relatives': '', 'Dates': '', 'Places': '', 'Evidence': '', 'Filters': '', 'Tree': ''}, self.badges())
        self.assertEqual(0, page.locator('details.filter-group[open]').count())
        self.assertFalse(page.get_by_role('button', name='Clear search and filters').is_visible())
        female = self.gender('Female')
        self.axe()
        # Gender reads the recorded sex: the rejected claim, the private one and the other value count as neither.
        for label, expected in (('Female', '2'), ('Male', '1'), ('Any', '42')):
            self.gender(label).check()
            self.assertEqual(f'{expected} of 42', self.count(), label)
        female.check()
        self.assertEqual({'person:01', 'person:03'}, set(page.locator('[data-person-id]:visible').evaluate_all('rows => rows.map(r => r.dataset.personId)')))
        self.assertEqual({'sex': 'F'}, self.query())
        self.assertEqual('1', self.badges()['Name'])
        # Read out with the pill as "Name (1 on)".
        self.assertEqual('Name1 (1 on)', page.locator('details.filter-group > summary', has_text='Name').text_content())
        self.reset()
        self.assertEqual('42 of 42', self.count())
        self.assertEqual({}, self.query())

        # A father or mother is a parent recorded as male or female: the demo records the sex of six people, two of them mothers.
        # Sixteen people have children (Bram Alder's only child link is disproved, so not him) and twenty-two no spouse.
        for label, expected in (('Missing father', '42'), ('Missing mother', '34'), ('Has descendants', '16'), ('No recorded spouse or partner', '22')):
            box = self.label(label)
            box.check()
            self.assertEqual(f'{expected} of 42', self.count(), label)
            box.uncheck()
        self.label('Missing mother').check()
        self.assertTrue(page.locator('[data-person-id="person:13"]').is_visible())
        self.label('No recorded spouse or partner').check()
        self.assertEqual('2', self.badges()['Filters'])
        self.reset()

        self.label('Dates apply to').select_option('birth')
        self.label('From year').fill('1810')
        self.label('To year').fill('1816')
        self.assertEqual('16 of 42', self.count())
        self.assertIn('16 matches of 42 people · 1–16 shown', page.locator('.result-count').inner_text())
        self.reset()
        self.label('Dates apply to').select_option('death')
        self.label('From year').fill('1899')
        self.assertEqual('6 of 42', self.count())
        # The years are read in order, so a range written backwards still matches.
        self.label('To year').fill('1898')
        self.assertEqual('6 of 42', self.count())
        self.reset()
        # The place filter matches any recorded place, in part and without regard to case.
        self.label('Location', exact=True).fill('lantern')
        self.assertEqual('31 of 42', self.count())
        self.label('Dates apply to').select_option('birth')
        self.label('From year').fill('1842')
        self.label('To year').fill('1847')
        self.assertEqual('4 of 42', self.count())
        # Any record: every event year, so no one with a Lanternford event has one in 1700-1750.
        self.label('Dates apply to').select_option('')
        self.label('From year').fill('1700')
        self.label('To year').fill('1750')
        self.assertEqual('0 of 42', self.count())
        self.assertIn('0 matches of 42 people · none shown', page.locator('.result-count').inner_text())
        self.assertEqual({'Name': '', 'Relatives': '', 'Dates': '2', 'Places': '1', 'Evidence': '', 'Filters': '', 'Tree': ''}, self.badges())
        self.assertEqual({'place': 'lantern', 'year_from': '1700', 'year_to': '1750'}, self.query())

    def test_the_page_address_keeps_every_filter(self):
        self.open('demo')
        page = self.page
        page.get_by_role('searchbox', name='Search people').fill('Cairn')
        self.label('Last name', exact=True).fill('cairn')
        self.label('Dates apply to').select_option('birth')
        self.label('From year').fill('1784')
        self.label('Location', exact=True).fill('Willowmere')
        self.label('No recorded spouse or partner').check()
        self.label('Claims').select_option('unassessed')
        page.get_by_role('button', name='Birth', exact=True).click()
        shown = self.count()
        self.assertEqual('3 of 42', shown)
        address = page.url
        self.assertEqual({'q': 'Cairn', 'last': 'cairn', 'date_type': 'birth', 'year_from': '1784', 'place': 'Willowmere', 'no_spouse': '1',
                          'evidence': 'unassessed', 'sort': 'birth'}, self.query())
        # Shared or reloaded, the address restores the same view, each menu's pill counting its filters on.
        other = self.context.new_page()
        other.goto(address, wait_until='networkidle')
        other.locator('.pagination').wait_for()
        self.assertEqual(shown, self.shown(other.locator('.result-count').inner_text()))
        self.assertEqual({'Name': '1', 'Relatives': '', 'Dates': '2', 'Places': '1', 'Evidence': '1', 'Filters': '1', 'Tree': ''}, self.badges(other))
        self.assertEqual('Cairn', other.get_by_role('searchbox', name='Search people').input_value())
        self.assertEqual('cairn', self.label('Last name', other, exact=True).input_value())
        self.assertEqual('birth', self.label('Dates apply to', other).input_value())
        self.assertEqual('1784', self.label('From year', other).input_value())
        self.assertEqual('Willowmere', self.label('Location', other, exact=True).input_value())
        self.assertTrue(self.label('No recorded spouse or partner', other).is_checked())
        self.assertFalse(self.label('Missing father', other).is_checked())
        self.assertEqual('Birth ↑', other.locator('th[aria-sort="ascending"]').text_content())
        self.assertEqual('Birth: oldest first', other.get_by_label('Sort results').evaluate('s => s.selectedOptions[0].textContent'))
        self.assertEqual(0, other.locator('th[aria-sort="descending"]').count())
        other.close()
        # Clearing keeps the sort and any parameter the catalogue does not own; an older year range is read as a birth range.
        self.open('demo', '?sort=death&from=elsewhere&birth_from=1810')
        self.assertEqual('22 of 42', self.count())
        self.assertEqual({'sort': 'death', 'from': 'elsewhere', 'date_type': 'birth', 'year_from': '1810'}, self.query())
        self.reset()
        self.assertEqual({'sort': 'death', 'from': 'elsewhere'}, self.query())
        # An unknown value is ignored rather than filtering everyone out; "no parent recorded" is read as missing both.
        self.open('demo', '?sex=X&surname=Nobody&no_parent=1')
        self.assertEqual('34 of 42', self.count())
        self.assertTrue(self.gender('Any').is_checked())
        self.assertEqual({'missing_father': '1', 'missing_mother': '1'}, self.query())
        self.assertEqual('Individual ↑', self.page.locator('th[aria-sort="ascending"]').text_content())

    def test_each_filter_on_the_large_catalogue_built_from_the_data(self):
        self.open('large')
        page = self.page
        self.assertEqual('400 of 400', self.count())
        male = self.gender('Male')
        self.axe()
        male.check()
        self.assertEqual('100 of 400', self.count())
        self.assertIn('Person 0001 Fable', page.locator('[data-person-id]:visible').first.inner_text())
        self.gender('Female').check()
        self.assertEqual('100 of 400', self.count())
        self.reset()
        # Person n's parent is person (n - 1) / 2, a mother when that number is a multiple of four and a father one more.
        for label, expected in (('Missing father', '300'), ('Missing mother', '300'), ('Has descendants', '200'), ('No recorded spouse or partner', '392')):
            box = self.label(label)
            box.check()
            self.assertEqual(f'{expected} of 400', self.count(), label)
            box.uncheck()
        self.label('Missing father').check()
        self.label('Missing mother').check()
        self.assertEqual('200 of 400', self.count())
        self.reset()
        self.label('Dates apply to').select_option('birth')
        self.label('From year').fill('1700')
        self.label('To year').fill('1709')
        self.assertEqual('30 of 400', self.count())
        self.label('Dates apply to').select_option('death')
        self.label('From year').fill('1750')
        self.label('To year').fill('1759')
        self.assertEqual('3 of 400', self.count())  # p0000, p0150 and p0300
        self.reset()
        self.label('Location', exact=True).fill('Inventia')
        self.assertEqual('131 of 400', self.count())  # every third place, less two hamlets recorded without a country
        self.label('Location', exact=True).fill('hamlet')
        self.assertEqual('8 of 400', self.count())
        # Someone beyond the written-out first page is found and shown like the written rows.
        self.label('Location', exact=True).fill('Hamlet 0350')
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
        self.assertEqual('Surname: Fable (400) Remove', self.filter(self.page.locator('.catalogue-surname-filter')).text_content())


if __name__ == '__main__':
    unittest.main()
