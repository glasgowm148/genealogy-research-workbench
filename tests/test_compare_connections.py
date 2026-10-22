"""Compare and connections: one-line GET forms, preset questions, and (opt-in, in a browser) readable results."""
from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import AccessLevel as A, Confidence as C, Event, LivingStatus as L, Name, Person, Place, Relationship
from genealogy.site import build_site

SECRET = "SECRET-Withheld Fable"


def person(pid, name, born, place=None, access=A.PUBLIC):
    return [Person(pid, names=[Name(name, surname=name.split()[-1])], living=L.DECEASED, sensitivity=access, event_ids=[f"{pid}-b"]),
            Event(f"{pid}-b", "birth", date=str(born), place_id=place, participant_ids=[pid], sensitivity=access)]


def link(rid, subject, obj, kind="parent", confidence=C.DOCUMENTED, access=A.PUBLIC):
    return Relationship(rid, subject, obj, kind, confidence=confidence, sensitivity=access)


def forms_case():
    """Ada Fable's line of four generations, an unassessed fifth, her probable spouse Edda Vale and Edda's possible son Finn."""
    case = ResearchCase("fictional-forms", "Fictional forms")
    records = [Place("pl-town", "Fableton", sensitivity=A.PUBLIC), Place("pl-secret", "SECRET-PLACE", sensitivity=A.PRIVATE),
               *person("p0001", "Ada Fable", 1800, "pl-town"), *person("p0002", "Bram Fable", 1825, "pl-town"),
               *person("p0003", "Cora Fable", 1850), *person("p0004", "Dell Fable", 1875), *person("p0007", "Gil Fable", 1900),
               *person("p0005", "Edda Vale", 1802), *person("p0006", "Finn Vale", 1830),
               link("r-ba", "p0002", "p0001"), link("r-cb", "p0003", "p0002"), link("r-dc", "p0004", "p0003"),
               link("r-gd", "p0007", "p0004", confidence=C.UNKNOWN),
               link("r-ae", "p0001", "p0005", "spouse", C.PROBABLE), link("r-fe", "p0006", "p0005", confidence=C.POSSIBLE),
               *person("p0900", SECRET, 1880, "pl-secret", access=A.PRIVATE), link("r-secret", "p0900", "p0007", access=A.PRIVATE)]
    for record in records:
        case.add(record)
    return case


class FormPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.temp.name)
        case = forms_case()
        assert validate_case(case) == []
        build_site(case, ProjectConfig(name="Fictional forms"), cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def text(self, path):
        return (self.out / path).read_text()

    def test_each_page_is_one_get_form_that_names_both_people_without_javascript(self):
        for route, hook, submit in (("compare.html", "compare", "Compare"), ("connections.html", "connection", "Find the connection →")):
            html = self.text(route)
            self.assertIn(f'<form class="person-form" method="get" action="{route}" data-person-form>', html)
            self.assertIn(f'<label>First person <select name="a" data-{hook}-a><option value="">Choose a person</option><option value="p0001">Ada Fable</option>', html)
            self.assertIn(f'<select name="b" data-{hook}-b>', html)
            self.assertIn(f'<button type="submit" class="button">{submit}</button>', html)
            self.assertIn('data-person-swap hidden aria-label="Swap the two people"', html)  # shown by the script
            self.assertIn('<a href="catalogue.html">Browse the name index →</a>', html)
            self.assertNotIn("Browse dossiers", html)
            self.assertNotIn("Interactive results require JavaScript", html)
            self.assertIn("<noscript>", html)
        self.assertIn("Compare two people&#39;s recorded dates, names, places, relatives and claims side by side.", self.text("compare.html"))
        self.assertIn("Choose two people to see the shortest route between them", self.text("connections.html"))

    def test_connections_offers_a_threshold_and_two_options(self):
        html = self.text("connections.html")
        self.assertIn('Evidence threshold <select name="evidence" data-connection-evidence><option value="any">Any recorded link, including unassessed</option>'
                      '<option value="probable">Probable and above</option><option value="documented">Documented only</option></select>', html)
        self.assertIn('<input type="checkbox" name="partners" value="1" checked data-connection-partners> Allow connections through partnership', html)
        self.assertIn('<input type="checkbox" name="uncertain" value="1" data-connection-uncertain> Include uncertain relationships', html)

    def presets(self, route):
        block = re.search(r'<h2>Start with a known question</h2><ul class="preset-pairs">(.*?)</ul>', self.text(route))
        self.assertIsNotNone(block, route)
        return re.findall(r'<li><a href="' + re.escape(route) + r'\?a=([^&"]+)&amp;b=([^"]+)">([^<]+)</a> <span class="meta">· ([^<]+)</span></li>', block[1])

    def test_connection_presets_are_the_longest_paths_the_default_settings_find(self):
        # Finn's only link is possible, so the default search cannot reach him; Gil's unassessed link counts.
        presets = self.presets("connections.html")
        self.assertEqual(("p0007", "p0005", "Gil Fable and Edda Vale", "5 steps"), presets[0])
        self.assertLessEqual(len(presets), 3)
        self.assertEqual(len(presets), len({(a, b) for a, b, *_ in presets}))
        self.assertTrue(all("p0006" not in (a, b) for a, b, *_ in presets))

    def test_compare_presets_pair_people_who_share_a_surname(self):
        presets = self.presets("compare.html")
        # One pair per surname first, then more from the largest group.
        self.assertEqual([("p0001", "p0002", "Ada Fable and Bram Fable", "both Fable"), ("p0005", "p0006", "Edda Vale and Finn Vale", "both Vale"),
                          ("p0003", "p0004", "Cora Fable and Dell Fable", "both Fable")], presets)

    def test_every_place_has_a_link_for_compare_and_withheld_records_stay_out(self):
        script = self.text("data/site-data.js")
        data = json.loads(script[script.index("{"):script.rindex("}") + 1])
        page = data["site"]["place_routes"]["pl-town"]
        self.assertTrue((self.out / page.partition("#")[0]).is_file())
        self.assertNotIn("pl-secret", data["site"]["place_routes"])
        for path in self.out.rglob("*"):
            if path.is_file():
                text = path.read_text(errors="replace")
                for secret in (SECRET, "SECRET-PLACE", "p0900", "r-secret"):
                    self.assertNotIn(secret, text, path)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@unittest.skipUnless(os.environ.get('GENEALOGY_BROWSER_TESTS') == '1',
                     'Run make browser-check with the browser extra installed')
class FormBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        build_site(forms_case(), ProjectConfig(name="Fictional forms"), root / "site")
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(root)))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}/site/'
        cls.pw = sync_playwright().start()
        executable = os.environ.get('GENEALOGY_BROWSER_EXECUTABLE')
        cls.browser = cls.pw.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.temp.cleanup()

    def setUp(self):
        self.page = self.browser.new_page(viewport={'width': 1280, 'height': 900})
        self.errors = []
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))
        self.page.on('console', lambda m: self.errors.append(m.text) if m.type == 'error' else None)

    def tearDown(self):
        self.assertEqual([], self.errors)
        self.page.close()

    def result(self):
        return self.page.locator('#connection-result')

    def axe(self, label):
        if not os.environ.get('GENEALOGY_AXE_PATH'):
            return
        self.page.add_script_tag(content=Path(os.environ['GENEALOGY_AXE_PATH']).read_text(encoding='utf-8'))
        violations = self.page.evaluate("async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                                        "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations.map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
        self.assertEqual([], violations, label)

    def test_connection_reads_as_sentences_with_a_summary_and_evidence(self):
        page = self.page
        page.goto(self.base + 'connections.html?a=p0004&b=p0001')
        self.assertEqual('Dell Fable is a great-grandchild of Ada Fable.', page.locator('.connection-summary').inner_text())
        steps = page.locator('.connection-steps > li')
        self.assertEqual(3, steps.count())
        self.assertEqual(['Dell Fable is the child of Cora Fable.', 'Cora Fable is the child of Bram Fable.', 'Bram Fable is the child of Ada Fable.'],
                         [steps.nth(i).locator('p').first.inner_text() for i in range(3)])
        self.assertIn('Documented', steps.first.inner_text())
        # Each step links to the relationship's entry, with its assessment and claims, on the dossier.
        evidence = steps.first.get_by_role('link', name='Evidence that Dell Fable is the child of Cora Fable')
        href = evidence.get_attribute('href')
        evidence.click()
        page.wait_for_load_state()
        anchor = href.partition('#')[2]
        self.assertTrue(anchor.startswith('r-'))
        self.assertEqual(1, page.locator(f'[id="{anchor}"]').count())
        self.assertIn('Cora Fable', page.locator(f'[id="{anchor}"]').inner_text())
        # Swap: the other way round, and the address follows.
        page.goto(self.base + 'connections.html?a=p0004&b=p0001')
        page.get_by_role('button', name='Swap the two people').click()
        self.assertEqual('Ada Fable is a great-grandparent of Dell Fable.', page.locator('.connection-summary').inner_text())
        self.assertIn('?a=p0001&b=p0004', page.url)
        self.assertEqual('Ada Fable', page.get_by_role('combobox', name='Find the first person').input_value())
        # A route through a shared ancestor says who it is.
        page.goto(self.base + 'connections.html?a=p0004&b=p0005')
        self.assertIn('are connected in 4 steps', page.locator('.connection-summary').inner_text())
        self.assertIn('Ada Fable is the spouse of Edda Vale.', self.result().inner_text())
        self.axe('connections result')

    def test_threshold_and_options_constrain_the_search(self):
        page = self.page
        page.goto(self.base + 'connections.html?a=p0006&b=p0001')
        # Finn's only link is possible: left out by default, with a pointer to the setting that finds it.
        self.assertIn('No connection with these settings. A 2-step route exists', self.result().inner_text())
        page.get_by_label('Include uncertain relationships').check()
        self.assertIn('Finn Vale is the child of Edda Vale.', self.result().inner_text())
        self.assertIn('Edda Vale is the spouse of Ada Fable.', self.result().inner_text())
        self.assertIn('Possible', self.result().inner_text())
        self.assertIn('evidence=any&partners=1&uncertain=1', page.url)
        page.get_by_label('Allow connections through partnership').uncheck()
        self.assertIn('No connection with these settings', self.result().inner_text())
        # The settings travel in the address and come back with it.
        page.reload()
        self.assertFalse(page.get_by_label('Allow connections through partnership').is_checked())
        self.assertTrue(page.get_by_label('Include uncertain relationships').is_checked())
        # Gil's link to Dell is unassessed: "any" reaches him, "documented only" and "probable and above" do not.
        page.goto(self.base + 'connections.html?a=p0001&b=p0007')
        self.assertEqual('Ada Fable is a 2nd great-grandparent of Gil Fable.', page.locator('.connection-summary').inner_text())
        self.assertIn('Unassessed tree link', self.result().inner_text())
        for level in ('documented', 'probable'):
            page.get_by_label('Evidence threshold').select_option(level)
            self.assertIn('No connection with these settings', self.result().inner_text())
            self.assertIn(f'evidence={level}', page.url)
        # A dossier's ?a= link keeps the defaults.
        page.goto(self.base + 'connections.html?a=p0001')
        self.assertTrue(page.get_by_label('Allow connections through partnership').is_checked())
        self.assertEqual('any', page.get_by_label('Evidence threshold').input_value())

    def test_one_box_per_side_with_examples_and_a_submit_button(self):
        page = self.page
        for route in ('compare.html', 'connections.html'):
            page.goto(self.base + route)
            first, second = (page.get_by_role('combobox', name=f'Find the {n} person') for n in ('first', 'second'))
            self.assertEqual('e.g. Ada Fable', first.get_attribute('placeholder'))
            self.assertEqual('e.g. Bram Fable', second.get_attribute('placeholder'))
            self.assertEqual(2, page.locator('[data-person-form] [role=combobox]').count())
            self.assertEqual(0, page.locator('[data-person-form] select[name=a]:visible, [data-person-form] select[name=b]:visible').count())
            first.fill('ada')
            page.keyboard.press('Enter')
            page.locator('[data-person-form] button[type=submit]').click()
            self.assertTrue(second.evaluate('e => e === document.activeElement'), route)  # the empty side is next
            second.fill('dell')
            page.keyboard.press('Enter')
            self.assertIn('?a=p0001&b=p0004', page.url)
            self.axe(route)
        # A preset question opens its pair.
        page.goto(self.base + 'connections.html')
        page.locator('.preset-pairs a').first.click()
        page.wait_for_url('**/connections.html?a=p0007&b=p0005')
        self.assertIn('are connected in 5 steps', page.locator('.connection-summary').inner_text())

    def test_compare_marks_shared_values_and_links_places_and_relatives(self):
        page = self.page
        for width in (1280, 390):
            page.set_viewport_size({'width': width, 'height': 900})
            page.goto(self.base + 'compare.html?a=p0001&b=p0002')
            out = page.locator('#compare-result')
            self.assertEqual(2, out.locator('.comparison .card').count())
            self.assertIn('In common: 1 surname and 1 place.', out.locator('.compare-summary').inner_text())
            self.assertIn('Recorded link: Ada Fable is the parent of Bram Fable (Documented).', out.inner_text())
            card = out.locator('.comparison .card').first
            place = card.locator('.value-pills li.shared a', has_text='Fableton')
            self.assertTrue(place.get_attribute('href').startswith('places/'))
            self.assertIn('both', card.locator('.value-pills li.shared', has_text='Fableton').text_content())  # shown in capitals
            self.assertTrue(card.locator('.value-pills a', has_text='Edda Vale').get_attribute('href').startswith('people/'))
            self.assertEqual('1800', card.locator('[data-date]').first.get_attribute('data-date'))
            # The name is the card's heading link; no second link repeats it.
            self.assertEqual(1, card.locator('h2 a').count())
            self.assertEqual(0, card.locator(':scope > a').count())
            self.assertEqual(f'{self.base}connections.html?a=p0001&b=p0002', out.get_by_role('link', name='Find how they are connected →').evaluate('a => a.href'))
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width + 1)
            self.axe(f'compare {width}')


if __name__ == "__main__":
    unittest.main()
