"""Each source lists what it supports, and the sources page groups sources by record type."""
from __future__ import annotations

from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Citation, Claim, ClaimStatus, Event, Evidence, Finding, LivingStatus as L, Name,
                              Person, Relationship, Source)
from genealogy.site import CITED_FOR_LIMIT, _anchor, build_site
from genealogy.sitecheck import check_site

TYPES_TOML = '''
[source_types.parish_register]
label = "Parish registers"
note = "A register entry names the parents as the minister heard them."

[source_types.banns]
note = "Banns alone do not prove a wedding took place."
'''


def config(directory: Path, extra: str = TYPES_TOML) -> ProjectConfig:
    path = directory / "genealogy.toml"
    path.write_text('[project]\nname = "Fictional sources"\n' + extra, encoding="utf-8")
    return ProjectConfig.load(path)


def person(pid: str, name: str, sensitivity=A.PUBLIC) -> Person:
    return Person(pid, names=[Name(name, surname="Fable")], living=L.DECEASED, sensitivity=sensitivity)


def case() -> ResearchCase:
    c = ResearchCase("fictional-sources", "Fictional sources")
    c.add_many([
        person("ada", "Ada Fable"), person("bram", "Bram Fable"), person("cora", "Cora Fable"), person("dan", "Dan Fable"),
        person("hidden", "SECRET-PERSON Fable", A.PRIVATE),
        Source("register", "Invented parish register", "Parish register", sensitivity=A.PUBLIC),
        Source("banns-book", "Invented banns book", "banns", sensitivity=A.PUBLIC),
        Source("letters", "Invented letters", "letter", sensitivity=A.PUBLIC),
        Source("uncited", "Invented uncited ledger", "letter", sensitivity=A.PUBLIC),
        Citation("entry-1", "register", locator="entry 1", sensitivity=A.PUBLIC),
        Citation("entry-2", "register", locator="entry 2", sensitivity=A.PUBLIC),
        Citation("banns-1", "banns-book", locator="folio 3", sensitivity=A.PUBLIC),
        Citation("letter-1", "letters", locator="letter 7", sensitivity=A.PUBLIC),
        Claim("ada-born", "ada", "birth", "1801", citation_ids=["entry-1"], status=ClaimStatus.SUPPORTED, sensitivity=A.PUBLIC),
        # Cited only through an evidence assessment.
        Claim("ada-trade", "ada", "occupation", "weaver", status=ClaimStatus.SUPPORTED, sensitivity=A.PUBLIC),
        Evidence("ada-trade-e", "ada-trade", "entry-2", "The entry names her trade.", sensitivity=A.PUBLIC),
        Claim("bram-baptised", "bram", "baptism", "1803", citation_ids=["entry-2"], status=ClaimStatus.SUPPORTED, sensitivity=A.PUBLIC),
        Claim("cora-secret", "cora", "residence", "SECRET-CLAIM Harbour Row", citation_ids=["entry-1"], sensitivity=A.PRIVATE),
        Claim("hidden-born", "hidden", "birth", "1805", citation_ids=["entry-1"], sensitivity=A.PUBLIC),
        Event("banns-event", "marriage banns", date="1825", participant_ids=["ada", "dan"], sensitivity=A.PUBLIC),
        Claim("banns-date", "banns-event", "date", "1825", citation_ids=["banns-1"], sensitivity=A.PUBLIC),
        Relationship("ada-parent", "ada", "bram", "parent", claim_ids=["ada-parent-claim"], sensitivity=A.PUBLIC),
        Claim("ada-parent-claim", "ada", "parent", "Bram Fable", citation_ids=["letter-1"], sensitivity=A.PUBLIC),
        Finding("banns-finding", "The banns name Ada and Dan.", related_ids=["ada", "dan"], citation_ids=["banns-1"],
                status="reviewed", sensitivity=A.PUBLIC),
    ])
    return c


def card(html: str, sid: str) -> str:
    start = html.index(f'id="{_anchor(sid)}"')
    end = html.find('<article class="record-card', start)
    return html[start:end if end > 0 else len(html)]


class SourceSupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        root = Path(cls.directory.name)
        cls.case = case()
        assert validate_case(cls.case) == [], validate_case(cls.case)
        cls.out = root / "site"
        build_site(cls.case, config(root), cls.out)
        cls.sources = (cls.out / "sources.html").read_text()

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_a_source_lists_the_people_findings_and_family_links_it_supports(self):
        register = card(self.sources, "register")
        self.assertIn("<h4>Cited for</h4>", register)
        people = re.findall(r'<li><a href="(people/[^"]+)">([^<]+)</a> <span class="meta">— ([^<]+)</span></li>', register)
        self.assertEqual([("Ada Fable", "birth, occupation"), ("Bram Fable", "baptism")], [(name, what) for _, name, what in people])
        self.assertNotIn("Findings", register)
        banns = card(self.sources, "banns-book")
        # A claim about an event is cited for the event's people.
        self.assertEqual(["Ada Fable", "Dan Fable"], re.findall(r'<li><a href="people/[^"]+">([^<]+)</a> <span class="meta">— date</span>', banns))
        self.assertIn(f'<dt>Findings</dt><dd><ul><li><a href="research.html#{_anchor("banns-finding")}">The banns name Ada and Dan.</a></li>', banns)
        letters = card(self.sources, "letters")
        self.assertIn(f'<dt>Family links</dt><dd><ul><li><a href="tree.html#{_anchor("ada-parent")}">Bram Fable is a parent of Ada Fable</a></li>', letters)
        self.assertNotIn("Cited for", card(self.sources, "uncited"))
        self.assertEqual([], check_site(self.out)["broken"])

    def test_a_withheld_claim_or_person_is_never_cited_for(self):
        self.assertNotIn("Cora Fable", card(self.sources, "register"))
        for path in self.out.rglob("*"):
            if path.is_file():
                text = path.read_text(errors="ignore")
                for secret in ("SECRET-CLAIM", "SECRET-PERSON", "cora-secret", "hidden-born"):
                    self.assertNotIn(secret, text, path)

    def test_the_sources_page_counts_each_record_type_and_prints_its_caution(self):
        rows = re.findall(r'<tr><td><a href="#(type-[a-z0-9-]+)">([^<]+)</a></td><td>(\d+)</td><td>(\d+)</td><td>(\d+)</td></tr>', self.sources)
        self.assertEqual([("type-letter", "Letter", "2", "1", "1"), ("type-banns", "Banns", "1", "1", "2"),
                          ("type-parish-register", "Parish registers", "1", "2", "2")], rows)
        for anchor, label, *_ in rows:
            self.assertIn(f'<section class="source-type" id="{anchor}" data-source-type="{anchor[5:]}"><h2>{label}</h2>', self.sources)
        self.assertIn('<h2>Banns</h2><p class="note source-type-note"><strong>Reading these records:</strong> Banns alone do not prove a wedding took place.</p>', self.sources)
        # Inside a type's section a source's title is one level down.
        self.assertIn('<h3>Invented parish register</h3>', self.sources)
        self.assertEqual(4, self.sources.count("data-source-id="))

    def test_a_much_cited_source_lists_the_first_people_and_counts_the_rest(self):
        c = ResearchCase("fictional-busy", "Fictional busy source")
        records = [Source("register", "Invented register", "register", sensitivity=A.PUBLIC),
                   Citation("entry", "register", sensitivity=A.PUBLIC)]
        for n in range(CITED_FOR_LIMIT + 5):
            records += [person(f"p{n:04d}", f"Person {n:04d} Fable"),
                        Claim(f"p{n:04d}-c", f"p{n:04d}", "birth", "1800", citation_ids=["entry"], sensitivity=A.PUBLIC)]
        c.add_many(records)
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            build_site(c, ProjectConfig(name="Fictional"), out)
            html = (out / "sources.html").read_text()
            self.assertEqual(CITED_FOR_LIMIT, html.count('<span class="meta">— birth</span>'))
            self.assertIn("Person 0019 Fable", html)
            self.assertNotIn("Person 0020 Fable", html)
            self.assertIn('<p class="meta">and 5 more people</p>', html)
            # One record type and no caution: the page is not split by type.
            self.assertNotIn("By record type", html)

    def test_configuration_accepts_source_types_and_rejects_bad_ones(self):
        with tempfile.TemporaryDirectory() as directory:
            loaded = config(Path(directory))
            self.assertEqual({"label": "Parish registers", "note": "A register entry names the parents as the minister heard them."},
                             loaded.source_types["parish_register"])
            self.assertEqual(loaded.source_types, loaded.to_dict()["source_types"])
            for bad, message in (('[source_types."Parish register"]\nlabel = "P"\n', "source type key"),
                                 ('[source_types.banns]\nnote = ""\n', "note must be a non-empty string"),
                                 ('[source_types.banns]\nlabel = 3\n', "label must be a non-empty string"),
                                 ('[source_types.banns]\nnote = "N"\ncolour = "red"\n', "unknown settings: colour"),
                                 ('[source_types]\nbanns = "N"\n', r"\[source_types.banns\] must be a table"),
                                 ('[source_types.banns]\n', "needs a label or a note"),
                                 ('[source_types.parish_register]\nlabel = "A"\n[source_types.parish-register]\nlabel = "B"\n', "names the same source type")):
                with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                    config(Path(directory), bad)


if __name__ == "__main__":
    unittest.main()
