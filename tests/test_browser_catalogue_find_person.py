"""Opt-in browser contract: the Find a person menus, their filtering, the result toolbar and the page address."""
from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import re
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlsplit

from genealogy.case import ResearchCase
from genealogy.config import ProjectConfig
from genealogy.site import build_site

from test_catalogue_find_person import GRADES, config, finder_case, finder_records  # tests/ is on the path under unittest discovery

EVERYONE = ['f01', 'f02', 'f03', 'f04', 'f05', 'f06', 'f07', 'f08', 'f09', 'f10']  # Ada, Bram, Cora, Dov, Esme, Finn, Gwen, Hugo, Iris, Jory


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@unittest.skipUnless(os.environ.get('GENEALOGY_BROWSER_TESTS') == '1',
                     'Run make browser-check with the browser extra installed')
class FindAPersonBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        from test_scale import large_case
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        build_site(finder_case(), config(), cls.root / 'finder')
        large = large_case()
        large.add_many(finder_records())
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

    def open(self, query='', site='finder'):
        self.page.goto(self.base + site + '/catalogue.html' + query, wait_until='networkidle')
        self.page.locator('.pagination').wait_for()

    def ids(self):
        return self.page.evaluate("[...document.querySelectorAll('tr[data-person-id]')].filter(r => !r.hidden).map(r => r.dataset.personId)")

    def menu(self, title):
        """A menu's panel, opened by its pill."""
        details = self.page.locator('details.filter-group', has=self.page.locator('summary', has_text=title))
        if not details.evaluate('d => d.open'):
            details.locator('summary').click()
        return details.locator('.filter-panel')

    def query(self):
        return {key: value[0] for key, value in parse_qs(urlsplit(self.page.url).query).items()}

    def badges(self):
        return dict(self.page.locator('details.filter-group > summary').evaluate_all(
            "s => s.map(n => [n.firstChild.textContent, n.querySelector('.pill-count').textContent])"))

    def reset(self):
        self.page.get_by_role('button', name='Clear search and filters').click()
        self.assertEqual(EVERYONE, sorted(self.ids()))

    def axe(self):
        if not os.environ.get('GENEALOGY_AXE_PATH'):
            return
        self.page.add_script_tag(content=Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8'))
        violations = self.page.evaluate(
            "async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
            "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations.map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
        self.assertEqual([], violations)

    def test_the_header_and_the_menus_one_open_at_a_time(self):
        self.open()
        page = self.page
        self.assertEqual('Find a person', page.locator('h1').inner_text())
        self.assertEqual(['Browse the name index', 'Download research data'], page.locator('.catalogue-links a').all_inner_texts())
        self.assertEqual('Held and pending research · 6 items →', page.locator('.catalogue-held').inner_text())
        self.assertEqual('10 people in catalogue', page.locator('.catalogue-total').inner_text())
        self.assertEqual('Name, FableTree ID or any detail (e.g. Ada Fable, Fable-1, Lanternby, 1801)',
                         page.get_by_role('searchbox', name='Search people').get_attribute('placeholder'))
        self.assertEqual({'Name': '', 'Relatives': '', 'Dates': '', 'Places': '', 'Evidence': '', 'Filters': '', 'FableTree': ''}, self.badges())
        # The lists the script fills and every placeholder name public records only.
        shown = page.locator('form.catalogue-finder').evaluate(
            "f => [...f.querySelectorAll('option')].map(o => o.textContent + ' ' + o.value).concat([...f.querySelectorAll('[placeholder]')].map(i => i.placeholder)).join(' | ')")
        self.assertIn('Lanternby households', shown)
        self.assertNotIn('SECRET', shown)
        self.assertNotIn('secret', shown)
        name = self.menu('Name')
        self.assertEqual('Name', name.locator('h3').inner_text())
        self.assertTrue(name.get_by_label('First name(s)').is_visible())
        self.menu('Dates')
        page.wait_for_function("document.querySelectorAll('details.filter-group[open]').length === 1")  # the other closes on its toggle event
        self.assertFalse(name.is_visible())
        # Done closes the menu and returns to its pill; Escape does the same.
        page.locator('details.filter-group[open]').get_by_role('button', name='Done').click()
        self.assertEqual(0, page.locator('details.filter-group[open]').count())
        self.assertEqual('Dates', page.evaluate('document.activeElement.firstChild.textContent'))
        self.menu('Places')
        page.keyboard.press('Escape')
        self.assertEqual(0, page.locator('details.filter-group[open]').count())
        self.axe()

    def test_the_name_menu(self):
        self.open()
        name = self.menu('Name')
        name.get_by_label('First name(s)').fill('ada')
        self.assertEqual(['f01'], self.ids())
        self.reset()
        # Any recorded surname, folded across [names.variants]: Bram Fabel and Esme's married name count.
        name.get_by_label('Last name', exact=True).fill('fabel')
        self.assertEqual(['f01', 'f02', 'f05', 'f06', 'f07', 'f10'], sorted(self.ids()))
        name.get_by_label('Last name matches').select_option('birth')
        self.assertEqual(['f01', 'f02', 'f06', 'f07', 'f10'], sorted(self.ids()))  # Esme was born a Rook
        name.get_by_label('Last name matches').select_option('current')
        self.assertIn('f05', self.ids())
        self.assertEqual({'last': 'fabel', 'last_scope': 'current'}, self.query())
        self.assertEqual('2', self.badges()['Name'])
        self.reset()
        name.get_by_label('Full name').fill('fable ada')
        self.assertEqual(['f01'], self.ids())
        self.reset()
        # Gender: people with no recorded sex (Jory) match neither.
        for label, expected in (('Male', ['f02', 'f04', 'f06', 'f08']), ('Female', ['f01', 'f03', 'f05', 'f07', 'f09']), ('Any', EVERYONE)):
            name.get_by_role('radio', name=label, exact=True).check()  # ♂ and ♀ are read as Male and Female
            self.assertEqual(expected, sorted(self.ids()), label)
        self.assertEqual('Gender', name.locator('fieldset legend').inner_text())
        # Exact name spelling keeps the main search box from folding Fabel into Fable.
        self.page.get_by_role('searchbox', name='Search people').fill('fabel')
        self.assertEqual(EVERYONE, sorted(self.ids()))
        name.get_by_label('Exact name spelling').check()
        self.assertEqual(['f01', 'f02', 'f07', 'f09'], sorted(self.ids()))  # Bram, and those whose relatives include him
        self.assertEqual({'q': 'fabel', 'exact': '1'}, self.query())

    def test_the_relatives_menu_and_its_rows(self):
        self.open()
        panel = self.menu('Relatives')
        rows = panel.locator('.relative-row:visible')
        self.assertEqual(['spouse'], rows.evaluate_all('r => r.map(n => n.dataset.relation)'))
        panel.get_by_label('Spouse name').fill('dov')
        self.assertEqual(['f01'], self.ids())
        # Choosing another relationship moves the name to it.
        panel.get_by_label('Relationship (spouse row)').select_option('child')
        self.assertEqual('dov', panel.get_by_label('Child name').input_value())
        self.assertEqual([], self.ids())  # nobody is recorded as Dov's parent
        self.assertEqual({'child': 'dov'}, self.query())
        panel.get_by_label('Child name').fill('finn')
        self.assertEqual(['f01', 'f04'], sorted(self.ids()))
        panel.get_by_role('button', name='+ Add relative').click()
        self.assertEqual(['child', 'spouse'], rows.evaluate_all('r => r.map(n => n.dataset.relation)'))
        # Each relationship can be used once: the menus offer only the free ones.
        self.assertTrue(panel.get_by_label('Relationship (spouse row)').locator('option[value="child"]').is_disabled())
        panel.get_by_label('Relationship (spouse row)').select_option('father')
        panel.get_by_label('Father name').fill('dov')
        self.assertEqual([], self.ids())  # nobody has Dov as father and Finn as child
        panel.get_by_label('Child name').fill('')
        self.assertEqual(['f06', 'f10'], sorted(self.ids()))
        panel.get_by_role('button', name='+ Add relative').click()
        panel.get_by_label('Relationship (spouse row)').select_option('mother')
        panel.get_by_label('Mother name').fill('fable ada')
        self.assertEqual(['f06'], self.ids())
        self.assertEqual('2', self.badges()['Relatives'])
        panel.get_by_role('button', name='Remove father').click()
        self.assertEqual(['f06'], self.ids())
        self.assertEqual({'mother': 'fable ada'}, self.query())
        for label, value, expected in (('Father', 'bram', ['f01', 'f07']), ('Mother', 'cora vale', ['f01', 'f07']), ('Sibling', 'gwen', ['f01'])):
            self.open(f'?{label.lower()}={value}')
            self.assertEqual(expected, sorted(self.ids()), label)
            self.assertEqual(value, self.menu('Relatives').get_by_label(f'{label} name').input_value())
        # All five in use: no relative left to add.
        self.open('?spouse=x&father=x&mother=x&child=x&sibling=x')
        self.assertTrue(self.menu('Relatives').get_by_role('button', name='+ Add relative').is_disabled())
        self.assertEqual('5', self.badges()['Relatives'])
        self.reset()
        self.assertEqual(['spouse'], self.page.locator('.relative-row:visible').evaluate_all('r => r.map(n => n.dataset.relation)'))

    def test_the_dates_and_places_menus(self):
        self.open()
        dates = self.menu('Dates')
        dates.get_by_label('From year').fill('1825')
        dates.get_by_label('To year').fill('1825')
        self.assertEqual(['f01', 'f04'], sorted(self.ids()))  # the marriage, by any record
        dates.get_by_label('Dates apply to').select_option('birth')
        self.assertEqual([], self.ids())
        dates.get_by_label('From year').fill('1802')
        dates.get_by_label('To year').fill('1800')
        self.assertEqual(['f01'], self.ids())  # the years are read in order
        dates.get_by_label('Dates apply to').select_option('death')
        dates.get_by_label('To year').fill('')
        self.assertEqual(['f01', 'f10'], self.ids())  # the two recorded deaths
        self.assertEqual({'date_type': 'death', 'year_from': '1802'}, self.query())
        self.assertEqual('2', self.badges()['Dates'])
        self.reset()
        places = self.menu('Places')
        regions = places.get_by_label('Country or region').locator('option').all_inner_texts()
        self.assertEqual(['Any region', 'At Sea', 'Fableland', 'Location unknown', 'The Inventian Isles'], regions)  # Willowby is filed under its Place.region; At Sea has no parts
        for kind, text, expected in (('', 'lanternby', ['f01', 'f06', 'f07']), ('death', 'willowby', ['f01']), ('marriage', 'mossford', ['f01', 'f04']),
                                     ('bio', 'mossbank', ['f01']), ('', 'mossbank', ['f01']), ('record', 'mossbank', [])):
            places.get_by_label('Location applies to').select_option(kind)
            places.get_by_label('Location', exact=True).fill(text)
            self.assertEqual(expected, sorted(self.ids()), (kind, text))
        self.reset()
        places.get_by_label('Country or region').select_option('Location unknown')
        self.assertEqual(['f02', 'f09'], sorted(self.ids()))  # events recorded, none placed
        places.get_by_label('Country or region').select_option('At Sea')
        self.assertEqual(['f10'], sorted(self.ids()))
        places.get_by_label('Country or region').select_option('Fableland')
        self.assertEqual(['f01', 'f04', 'f06', 'f07'], sorted(self.ids()))
        places.get_by_label('Exclude location').fill('inventia')
        self.assertEqual(['f04', 'f06', 'f07'], sorted(self.ids()))  # Ada died in Inventia
        places.get_by_label('Location applies to').select_option('birth')
        places.get_by_label('Exclude location').fill('inventia, north shire')
        self.assertEqual(['f04'], sorted(self.ids()))
        self.assertEqual({'place_type': 'birth', 'region': 'Fableland', 'exclude_place': 'inventia, north shire'}, self.query())
        self.assertEqual('3', self.badges()['Places'])

    def test_the_evidence_filters_and_tree_menus(self):
        self.open()
        evidence = self.menu('Evidence')
        group = evidence.get_by_label('Possible group')
        self.assertEqual(['Any group', 'Lanternby households', 'Rook family'], group.locator('option').all_inner_texts())
        group.select_option(label='Rook family')
        self.assertEqual(['f04', 'f05'], sorted(self.ids()))  # the study's group members
        self.assertEqual({'study': 'st-rook'}, self.query())
        self.reset()
        kinds = evidence.get_by_label('Record type')
        self.assertEqual(['Any record type', 'Census returns', 'Compiled_tree', 'Parish_register'], kinds.locator('option').all_inner_texts())
        kinds.select_option(label='Census returns')
        self.assertEqual(['f04'], self.ids())
        self.reset()
        quality = evidence.get_by_label('Source quality')
        for value, expected in (('original', ['f01']), ('derivative', ['f04']), ('authored', []), ('unknown', ['f05']),
                                ('tree_only', ['f02', 'f03', 'f06', 'f07', 'f08', 'f09', 'f10'])):
            quality.select_option(value)
            self.assertEqual(expected, sorted(self.ids()), value)
        self.reset()
        claims = evidence.get_by_label('Claims')
        for value, expected in (('supported', ['f01']), ('original', ['f01']), ('unassessed', [p for p in EVERYONE if p != 'f01'])):
            claims.select_option(value)
            self.assertEqual(expected, sorted(self.ids()), value)
        self.reset()
        filters = self.menu('Filters')
        self.assertEqual(['Surname and marriage', 'Family'], filters.locator('h4').all_text_contents())
        for label, expected in (('Fable at birth', ['f01', 'f02', 'f06', 'f07', 'f10']), ('Women who married a Fable', ['f05', 'f09']), ('Has suffix', ['f06']),
                                ('Missing father', ['f02', 'f03', 'f04', 'f05', 'f08', 'f09']), ('Missing mother', ['f02', 'f03', 'f04', 'f05', 'f08', 'f09', 'f10']),
                                ('Has descendants', ['f01', 'f02', 'f03', 'f04']), ('No recorded spouse or partner', ['f03', 'f05', 'f06', 'f07', 'f08', 'f10'])):
            box = filters.get_by_label(label)
            box.check()
            self.assertEqual(expected, sorted(self.ids()), label)
            box.uncheck()
        filters.get_by_label('Missing father').check()
        filters.get_by_label('Has descendants').check()
        self.assertEqual(['f02', 'f03', 'f04'], sorted(self.ids()))
        self.assertEqual({'missing_father': '1', 'has_children': '1'}, self.query())
        self.reset()
        tree = self.menu('FableTree')
        tree.get_by_label('No confirmed FableTree link').check()
        self.assertEqual(['f03', 'f04', 'f05', 'f06', 'f07', 'f08', 'f09', 'f10'], sorted(self.ids()))
        tree.get_by_label('No confirmed FableTree link').uncheck()
        # Pending: a finding not yet reviewed or applied changes a link to or from the person; Gwen's change is reviewed.
        tree.get_by_label('Needs updated on FableTree').check()
        self.assertEqual(['f01', 'f02', 'f04', 'f06', 'f08', 'f10'], sorted(self.ids()))
        tree.get_by_label('Needs updated on FableTree').uncheck()
        # A menu's label also holds its options' words ("Any relationship change"), so each is found by how its label starts.
        relationship, action, confidence = (tree.get_by_label(re.compile('^' + t)) for t in ('Changed relationship', 'Relationship change', 'New confidence'))
        for menu, value, expected in ((relationship, 'child', ['f02', 'f04', 'f08']), (relationship, 'spouse', ['f01', 'f04']), (relationship, 'mother', []),
                                      (action, 'topology', ['f01', 'f02', 'f04', 'f06', 'f10']), (action, 'add', ['f01', 'f02']),
                                      (action, 'replace', ['f04', 'f06', 'f10']), (action, 'regrade', ['f01', 'f04', 'f08', 'f10']),
                                      (confidence, 'strongly_supported', ['f01', 'f04']), (confidence, 'disproved', ['f08', 'f10']), (confidence, 'unrated', [])):
            menu.select_option(value)
            self.assertEqual(expected, sorted(self.ids()), value)
            menu.select_option('')
        # The three apply to one change together: Jory's and Finn's new fathers replace another link.
        relationship.select_option('father')
        action.select_option('replace')
        self.assertEqual(['f06', 'f10'], sorted(self.ids()))
        confidence.select_option('possible')
        self.assertEqual(['f10'], self.ids())
        self.assertEqual({'change_relationship': 'father', 'change_action': 'replace', 'change_confidence': 'possible'}, self.query())
        self.assertEqual('3', self.badges()['FableTree'])
        self.axe()

    def test_the_result_toolbar_groups_and_sorts(self):
        self.open()
        page = self.page
        total = page.locator('.result-total')
        self.assertEqual('All 10 people', total.inner_text())
        sort = page.get_by_label('Sort results')
        options = lambda: sort.locator('option').evaluate_all('o => o.filter(n => !n.hidden).map(n => n.textContent)')
        self.assertEqual(['Update priority: new fathers first', 'Update significance', 'Father changes: highest confidence', 'Name A–Z', 'Birth: oldest first', 'Birth: newest first', 'Death: oldest first', 'Death: newest first',
                          'Relationship changes: highest confidence', 'Relationship changes: lowest confidence'], options())
        sort.select_option('changes-desc')
        self.assertEqual(['f01', 'f02', 'f04', 'f06', 'f10', 'f08', 'f03', 'f05', 'f07', 'f09'], self.ids())
        sort.select_option('changes')
        self.assertEqual(['f08', 'f10', 'f04', 'f06', 'f01', 'f02', 'f03', 'f05', 'f07', 'f09'], self.ids())
        self.assertEqual({'sort': 'changes'}, self.query())
        sort.select_option('birth-desc')
        self.assertEqual([['Birth', 'descending']], page.locator('th[aria-sort]').evaluate_all("t => t.map(n => [n.firstChild.firstChild.textContent, n.getAttribute('aria-sort')])"))
        # A heading's other orders are named in the menu while chosen.
        page.get_by_role('button', name='Father', exact=True).click()
        self.assertEqual('Father: ascending', sort.evaluate('s => s.selectedOptions[0].textContent'))
        self.assertIn('Father: ascending', options())
        # Search: with a query, Best match is offered and chosen; the name that matches comes first.
        box = page.get_by_role('searchbox', name='Search people')
        box.fill('ada')
        self.assertEqual('Best match', options()[0])
        page.get_by_role('button', name='Search', exact=True).click()
        self.assertEqual('relevance', sort.input_value())
        self.assertEqual('f01', self.ids()[0])
        self.assertEqual(f'{len(self.ids())} results', total.inner_text())
        self.assertEqual({'q': 'ada', 'sort': 'relevance'}, self.query())
        box.fill('')
        self.assertEqual('name', sort.input_value())
        self.assertNotIn('Best match', options())
        # Group: by family branch, the earliest-born ancestor up the parent links.
        page.get_by_role('checkbox', name='Family branch').check()
        groups = page.locator('tbody tr.group th')
        self.assertEqual(['Descendants of Bram Fabel (b. 1775) · 4 people', 'Descendants of Cora Vale (b. 1778) · 1 person', 'Descendants of Dov Rook (b. 1799) · 2 people',
                          'Descendants of Esme Rook · 1 person', 'Descendants of Hugo Vale · 1 person', 'Descendants of Iris Rook · 1 person'], groups.all_text_contents())
        self.assertFalse(page.get_by_label('Location detail').is_visible())
        page.get_by_role('checkbox', name='Family branch').uncheck()
        page.get_by_role('checkbox', name='Location').check()
        detail = page.get_by_label('Location detail')
        self.assertEqual(['Country', 'County / area', 'Townland / locality'], detail.locator('option').all_inner_texts())
        self.assertIn('Fableland · 3 people', groups.all_text_contents())
        detail.select_option('2')
        self.assertEqual(['North Shire, Fableland · 3 people', 'Willowby, Inventia · 1 person', 'No birth place recorded · 6 people'], groups.all_text_contents())
        detail.select_option('3')
        self.assertIn('Lanternby, North Shire, Fableland · 3 people', groups.all_text_contents())
        self.assertEqual({'group_location': '1', 'location_detail': '3'}, self.query())
        page.get_by_role('checkbox', name='Family branch').check()
        self.assertIn('Lanternby, North Shire, Fableland · Descendants of Bram Fabel (b. 1775) · 3 people', groups.all_text_contents())
        # Grouping and the order are how the people are shown, so Clear keeps them.
        self.assertTrue(page.get_by_role('button', name='Clear search and filters').is_hidden())
        page.get_by_role('tab', name='Map', exact=True).click()
        self.assertFalse(detail.is_visible())
        self.assertEqual('All 10 people', total.inner_text())

    def test_the_page_address_restores_every_control(self):
        query = ('?q=fable&first=ada&last=fable&last_scope=birth&name=ada&sex=F&exact=1&spouse=dov&date_type=birth&year_from=1800&year_to=1802'
                 '&place_type=birth&place=lanternby&region=Fableland&exclude_place=inventia&study=st-lantern&record_type=parish-register&quality=original'
                 '&evidence=supported&born_surname=1&has_children=1&needs_update=1&change_relationship=father&change_action=add&change_confidence=documented'
                 '&sort=birth&group_branch=1&location_detail=2&group_location=1')
        self.open(query)
        self.assertEqual(['f01'], self.ids())
        self.assertEqual({'Name': '6', 'Relatives': '1', 'Dates': '3', 'Places': '4', 'Evidence': '4', 'Filters': '2', 'FableTree': '4'}, self.badges())
        self.assertEqual(dict(parse_qs(urlsplit(query).query, keep_blank_values=True)), {k: [v] for k, v in self.query().items()})
        self.assertEqual('dov', self.menu('Relatives').get_by_label('Spouse name').input_value())
        self.assertTrue(self.menu('Name').get_by_role('radio', name='Female').is_checked())
        self.assertEqual('2', self.page.get_by_label('Location detail').input_value())
        # A form sent without the script carries every control, empty ones too; the script reads it and tidies the address.
        self.open('?q=&first=ada&last=&last_scope=&sex=&spouse=&year_from=&place_type=')
        self.assertEqual(['f01'], self.ids())
        self.assertEqual({'first': 'ada'}, self.query())
        # Older addresses still work: the year ranges and "no parent recorded" are read into the new menus.
        self.open('?birth_from=1800&birth_to=1802&from=elsewhere')
        self.assertEqual(['f01'], self.ids())
        self.assertEqual({'date_type': 'birth', 'year_from': '1800', 'year_to': '1802', 'from': 'elsewhere'}, self.query())
        self.open('?no_parent=1')
        self.assertEqual({'missing_father': '1', 'missing_mother': '1'}, self.query())
        self.assertEqual(['f02', 'f03', 'f04', 'f05', 'f08', 'f09'], sorted(self.ids()))
        # A surname link from elsewhere on the site keeps everyone grouped under the surname, shown and removable in the Name menu.
        self.open('?surname=Fabel')
        self.assertEqual(['f01', 'f02', 'f06', 'f07', 'f10'], sorted(self.ids()))
        name = self.menu('Name')
        self.assertEqual('Surname: Fable (5, incl. Fabel) Remove', name.locator('.catalogue-surname-filter').text_content())
        self.assertEqual('1', self.badges()['Name'])
        self.assertEqual({'surname': 'Fable'}, self.query())
        name.get_by_role('button', name='Remove the surname filter').click()
        self.assertEqual(EVERYONE, sorted(self.ids()))
        self.assertEqual({}, self.query())
        self.assertFalse(name.locator('.catalogue-surname-filter').is_visible())

    def test_a_large_site_filters_everyone_from_the_data(self):
        self.open(site='large')
        self.assertEqual('All 410 people', self.page.locator('.result-total').inner_text())
        self.assertEqual(50, len(self.ids()))
        self.open('?born_surname=1&change_action=replace', site='large')
        self.assertEqual(['f06', 'f10'], sorted(self.ids()))
        # Every person is listed under "Fable" at birth, the 400 of the scale fixture with them.
        self.open('?born_surname=1', site='large')
        self.assertIn('405 matches of 410 people', self.page.locator('.result-count').inner_text())
        groups = self.menu('Evidence').get_by_label('Possible group').locator('option')
        self.assertEqual(403, groups.count())  # the 400 studies, the two in this fixture and Any group

    def test_wcag_aa_with_each_menu_open_at_both_widths(self):
        for width in (1440, 390):
            self.page.set_viewport_size({'width': width, 'height': 900})
            self.open('?group_location=1&group_branch=1&spouse=dov')
            for title in ('Name', 'Relatives', 'Dates', 'Places', 'Evidence', 'Filters', 'FableTree'):
                with self.subTest(width=width, menu=title):
                    self.menu(title)
                    self.axe()
                    self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width + 1)

    def test_without_javascript_the_menus_are_a_form(self):
        context = self.browser.new_context(java_script_enabled=False)
        try:
            page = context.new_page()
            page.goto(self.base + 'finder/catalogue.html')
            self.assertEqual(10, page.locator('tr[data-person-id]').count())
            self.assertEqual(7, page.locator('details.filter-group').count())
            page.locator('details.filter-group > summary', has_text='Relatives').click()
            # All five relatives' boxes, each labelled; the script adds the relationship menus and buttons.
            self.assertEqual(['Spouse name', 'Father name', 'Mother name', 'Child name', 'Sibling name'],
                             page.locator('details[open] .relative-row label').all_inner_texts())
            page.get_by_label('Father name').fill('bram')
            page.get_by_role('searchbox', name='Search people').fill('ada')
            page.get_by_role('button', name='Search', exact=True).click()
            page.wait_for_load_state()
            sent = parse_qs(urlsplit(page.url).query, keep_blank_values=True)
            self.assertEqual(['ada'], sent['q'])
            self.assertEqual(['bram'], sent['father'])
            self.assertEqual({'q', 'first', 'last', 'last_scope', 'name', 'sex', 'spouse', 'father', 'mother', 'child', 'sibling', 'date_type', 'year_from',
                              'year_to', 'place_type', 'place', 'region', 'exclude_place', 'study', 'record_type', 'quality', 'evidence', 'change_relationship',
                              'change_action', 'change_confidence'}, set(sent))  # unticked boxes are not sent
            # A static page cannot filter itself: the same first page is shown, with the note saying so.
            self.assertEqual(10, page.locator('tr[data-person-id]').count())
            self.assertIn('without JavaScript this page lists the people in name order', page.locator('form.catalogue-finder').inner_text())
        finally:
            context.close()


if __name__ == '__main__':
    unittest.main()
