"""research.html leads with open questions as cards; claims are short rows grouped by person."""
from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Citation, Claim, Confidence, Evidence, Finding, Hypothesis, LivingStatus as L, Name, Person,
                              ResearchQuestion, Search, Source, Study)
from genealogy.site import _anchor, build_site


def person(pid, name, sensitivity=A.PUBLIC):
    return Person(pid, names=[Name(name)], living=L.DECEASED, sensitivity=sensitivity)


def research_case():
    c = ResearchCase("fictional-notebook", "Fictional notebook")
    c.add_many([
        person("ada", "Ada Fable"), person("bram", "Bram Fable"), person("hidden", "SECRET-PERSON Fable", A.PRIVATE),
        Source("src", "Invented parish register", "register", sensitivity=A.PUBLIC),
        Citation("cit", "src", locator="folio 3", sensitivity=A.PUBLIC),
        Claim("ada-father", "ada", "father", "Bram Fable", citation_ids=["cit"], sensitivity=A.PUBLIC),
        Claim("ada-born", "ada", "birth", "1801", citation_ids=["cit"], sensitivity=A.PUBLIC),
        Claim("bram-born", "bram", "birth", "1770", citation_ids=["cit"], sensitivity=A.PUBLIC),
        Claim("hidden-born", "hidden", "birth", "SECRET-CLAIM 1790", sensitivity=A.PRIVATE),
        Evidence("ev-father", "ada-father", "cit", "The banns name a father Bram.", sensitivity=A.PUBLIC),
        # Listed out of priority order on purpose: the high-priority question leads.
        ResearchQuestion("q-normal", "Where did Bram Fable die?", related_ids=["bram"], sensitivity=A.PUBLIC),
        ResearchQuestion("q-high", "Who were Ada Fable's parents?", related_ids=["ada", "bram", "ada-father"], priority="high",
                         resolves="A baptism naming both parents.", next_record="Invented register, 1800–1802", sensitivity=A.PUBLIC),
        ResearchQuestion("q-done", "When was Ada Fable baptised?", related_ids=["ada"], status="resolved", sensitivity=A.PUBLIC),
        ResearchQuestion("q-secret", "SECRET-QUESTION about Ada", related_ids=["ada"], sensitivity=A.PRIVATE),
        Hypothesis("h-bram", "Ada's father was Bram Fable", related_ids=["ada"], confidence=Confidence.PROBABLE, sensitivity=A.PUBLIC),
        Finding("f-draft", "The banns name Bram as Ada's father.", related_ids=["ada"], evidence_ids=["ev-father"], recorded_on="2026-09-08",
                sensitivity=A.PUBLIC),
        Finding("f-done", "Bram lived in the parish in 1800.", related_ids=["bram"], status="reviewed", sensitivity=A.PUBLIC),
        Study("st", "Ada's parents", summary="Whether the banns describe Ada's father.", related_ids=["ada", "q-high"], sensitivity=A.PUBLIC),
        Search("se", search="Invented register, 1800–1805", result="Nothing found.", related_ids=["ada"], searched_on="2026-09-01",
               sensitivity=A.PUBLIC),
    ])
    return c


class ResearchPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.out = Path(cls.directory.name) / "site"
        c = research_case()
        assert validate_case(c) == [], validate_case(c)
        build_site(c, ProjectConfig(name="Fictional notebook"), cls.out)
        cls.page = (cls.out / "research.html").read_text()

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def dossier(self, pid):
        return next(p for p in (self.out / "people").glob("*.html") if f'data-person-id="{pid}"' in p.read_text()).read_text()

    def section(self, key, end):
        return self.page[self.page.index(f'<h2 id="{key}">'):self.page.index(f'<h2 id="{end}">')]

    def test_open_questions_come_first_then_hypotheses_findings_claims_and_the_log(self):
        order = [self.page.index(marker) for marker in ('class="research-counts"', '<h2 id="open-questions">Open questions</h2>', '<h2 id="hypotheses">Hypotheses</h2>',
                                                        '<h2 id="findings">Findings</h2>', '<h2 id="claims">Claims</h2>', '<h2 id="research-log">Research log</h2>')]
        self.assertEqual(sorted(order), order)

    def test_the_header_counts_open_work_and_links_to_each_section(self):
        counts = self.page[self.page.index('<nav class="research-counts"'):self.page.index("</nav>", self.page.index('class="research-counts"'))]
        for key, words in (("open-questions", "<strong>2</strong> open questions"), ("hypotheses", "<strong>1</strong> open hypothesis"),
                           ("findings", "<strong>1</strong> draft finding"), ("research-log", "<strong>1</strong> search logged")):
            self.assertIn(f'<a href="#{key}">{words}</a>', counts)
            self.assertIn(f'<h2 id="{key}">', self.page)

    def test_each_open_question_is_a_card_with_its_people_study_plan_and_linked_evidence(self):
        section = self.section("open-questions", "hypotheses")
        cards = re.findall(r'<li class="card question-card" id="([^"]+)" data-status="open" data-priority="(\w+)">', section)
        self.assertEqual([(_anchor("q-high"), "high"), (_anchor("q-normal"), "normal")], cards)  # highest priority first
        high = section[section.index(f'id="{_anchor("q-high")}"'):section.index(f'id="{_anchor("q-normal")}"')]
        self.assertIn('<p class="eyebrow">High priority</p><h3>Who were Ada Fable&#x27;s parents?</h3>', high)
        self.assertRegex(high, r'<p class="question-links"><strong>People:</strong> <a href="people/[^"]+">Ada Fable</a> · <a href="people/[^"]+">Bram Fable</a></p>')
        self.assertRegex(high, r'<strong>Study:</strong> <a href="studies/[^"]+">Ada&#x27;s parents</a>')
        self.assertIn('<dt>What would answer this</dt><dd>A baptism naming both parents.</dd><dt>Next record to check</dt><dd>Invented register, 1800–1802</dd>', high)
        evidence = high[high.index('<details class="question-evidence"><summary>Linked evidence and related research</summary>'):]
        self.assertIn(f'#{_anchor("ada-father")}">father: Bram Fable</a>', evidence)  # a linked claim, by what it says
        self.assertIn(f'href="research.html#{_anchor("h-bram")}">Ada&#x27;s father was Bram Fable</a>', evidence)  # work on the same people
        self.assertIn(f'href="research.html#{_anchor("f-draft")}">The banns name Bram as Ada&#x27;s father.</a>', evidence)
        self.assertNotIn("ada-father", re.sub(r'href="[^"]*"|id="[^"]*"', "", evidence))  # no raw ids

    def test_answered_questions_are_listed_after_the_cards_and_keep_their_address(self):
        section = self.section("open-questions", "hypotheses")
        closed = section[section.index('<h3 id="closed-questions">Answered or closed questions</h3>'):]
        self.assertIn(f'<li id="{_anchor("q-done")}" data-status="resolved">When was Ada Fable baptised?', closed)
        self.assertNotIn('question-card" id="' + _anchor("q-done"), section)
        self.assertNotIn("question-next", closed)

    def test_claims_are_short_rows_grouped_by_person_with_the_full_card_on_the_dossier(self):
        claims = self.section("claims", "research-log")
        self.assertNotIn("evidence-table", claims)
        self.assertNotIn("record-card", claims)
        groups = re.findall(r'<details class="claims-person"><summary>([^<]+) <span class="meta">· (\d+) claims?</span></summary>', claims)
        self.assertEqual([("Ada Fable", "2"), ("Bram Fable", "1")], groups)
        ada = self.dossier("ada")
        for cid in ("ada-father", "ada-born", "bram-born"):
            self.assertEqual(1, claims.count(f'<li id="{_anchor(cid)}">'), cid)
        self.assertRegex(claims, rf'<li id="{_anchor("ada-father")}"><a href="people/[^"#]+#{_anchor("ada-father")}">father: Bram Fable</a>')
        # The assessment keeps its anchor here and links to its row in the full card.
        self.assertRegex(claims, rf'<a id="{_anchor("ev-father")}" href="people/[^"#]+#{_anchor("ev-father")}">Supports: Invented parish register</a>')
        self.assertIn(f'<article class="record-card card" id="{_anchor("ada-father")}">', ada)
        self.assertIn(f'<tr id="{_anchor("ev-father")}">', ada)

    def test_every_link_into_the_notebook_lands_on_an_anchor(self):
        ids = set(re.findall(r'\bid="([^"]+)"', self.page))
        for path in self.out.rglob("*.html"):
            for target in re.findall(r'href="(?:\.\./)*research\.html#([^"]+)"', path.read_text()):
                self.assertIn(target, ids, f"{path.name} -> research.html#{target}")
        for target in re.findall(r'href="#([^"]+)"', self.page):
            self.assertIn(target, ids)

    def test_findings_are_compact_and_keep_their_anchor_and_status(self):
        findings = self.section("findings", "claims")
        self.assertIn('class="record-list findings-compact"', findings)
        self.assertIn(f'<li id="{_anchor("f-draft")}" data-status="draft"><h3>The banns name Bram as Ada&#x27;s father.</h3><p class="finding-meta"><span class="meta">2026-09-08</span>', findings)
        self.assertIn(f'<li id="{_anchor("f-done")}" data-status="reviewed">', findings)
        self.assertIn(">Evidence for father: Bram Fable</a>", findings)

    def test_withheld_questions_and_claims_are_in_no_output(self):
        for path in self.out.rglob("*"):
            if path.is_file():
                text = path.read_text(errors="ignore")
                for sentinel in ("SECRET-QUESTION", "SECRET-CLAIM", "SECRET-PERSON"):
                    self.assertNotIn(sentinel, text, f"{sentinel} in {path}")


@unittest.skipUnless(os.environ.get("GENEALOGY_BROWSER_TESTS") == "1", "Run make browser-check with the browser extra installed")
class ResearchPageBrowserTests(unittest.TestCase):
    def test_a_link_to_a_claim_row_opens_its_group_and_the_page_passes_axe(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(research_case(), ProjectConfig(name="Fictional notebook"), out)
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=os.environ.get("GENEALOGY_BROWSER_EXECUTABLE") or None)
                try:
                    for javascript in (True, False):
                        page = browser.new_context(java_script_enabled=javascript, viewport={"width": 390, "height": 800}).new_page()
                        page.goto((out / "research.html").as_uri() + "#" + _anchor("ev-father"))
                        self.assertTrue(page.evaluate(f'document.getElementById("{_anchor("ev-father")}").closest("details").open'), javascript)
                        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
                    if os.environ.get("GENEALOGY_AXE_PATH"):
                        page = browser.new_page()
                        page.goto((out / "research.html").as_uri())
                        page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
                        page.add_script_tag(content=Path(os.environ["GENEALOGY_AXE_PATH"]).read_text(encoding="utf-8"))
                        violations = page.evaluate("async () => (await axe.run(document, {runOnly: {type: 'tag', values: "
                                                   "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})).violations.map(v => `${v.id}: ${v.nodes[0].target.join(' ')}`)")
                        self.assertEqual([], violations)
                finally:
                    browser.close()


if __name__ == "__main__":
    unittest.main()
