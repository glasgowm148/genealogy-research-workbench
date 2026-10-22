"""Possible duplicates: an optional page of same-name pairs listed as leads to check, never as merges."""
from __future__ import annotations

from html import unescape
from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import AccessLevel as A, Event, LivingStatus as L, Name, Person, Relationship
from genealogy.site import build_site
from genealogy.sitecheck import check_site

from test_scale import PEOPLE, large_case

CAUTION = "Two records may describe one person, or two people who shared a name. Nothing here is a conclusion."


def person(pid, name, year=None, place=None, sensitivity=A.PUBLIC, **extra):
    """A person with an optional birth year and place; a place without a year is a residence."""
    records = [Person(pid, names=[name], living=L.DECEASED, event_ids=[f"{pid}-b"] if year or place else [], sensitivity=sensitivity, **extra)]
    if year or place:
        records.append(Event(f"{pid}-b", "birth" if year else "residence", date=str(year) if year else None, place_id=place,
                             participant_ids=[pid], sensitivity=sensitivity))
    return records


def planted() -> list:
    return [
        # Case and diacritics folded: Ada and ÁDA, two years apart.
        *person("p9001", Name("Ada Fable", surname="Fable"), 1801, "pl0001"),
        *person("p9002", Name("ÁDA Fable", surname="FABLE"), 1803),
        # A different given name with the same surname, year and place is never paired.
        *person("p9003", Name("Ida Fable", surname="Fable"), 1801, "pl0001"),
        # A listed spelling of the surname is the same surname.
        *person("p9004", Name("Wren Fabel", surname="Fabel"), 1820),
        *person("p9005", Name("Wren Fable", surname="Fable"), 1821),
        # No birth year, but a place in common; the third Tobin shares neither a place nor a close year.
        *person("p9006", Name("Tobin Fable", surname="Fable"), None, "pl0010"),
        *person("p9007", Name("Tobin Fable", surname="Fable"), 1850, "pl0010"),
        *person("p9008", Name("Tobin Fable", surname="Fable"), 1860, "pl0020"),
        # The first given name comes from ``given`` when it is recorded.
        *person("p9009", Name("Mara Ellen Fable", given="Mara Ellen", surname="Fable"), 1870),
        *person("p9010", Name("Mara Fable", surname="Fable"), 1872),
        # Three years apart: not paired.
        *person("p9011", Name("Pell Fable", surname="Fable"), 1900),
        *person("p9012", Name("Pell Fable", surname="Fable"), 1903),
        # Already linked by a recorded relationship: not paired.
        *person("p9013", Name("Cass Fable", surname="Fable"), 1880),
        *person("p9014", Name("Cass Fable", surname="Fable"), 1881),
        Relationship("r9013", "p9013", "p9014", "sibling", sensitivity=A.PUBLIC),
        # Withheld: never paired with Ada, and nothing about it reaches any output.
        *person("p9099", Name("Ada SECRET-NAME Fable", surname="Fable"), 1802, "pl0001", A.PRIVATE, notes="SECRET-NOTES"),
    ]


EXPECTED = {("p9001", "p9002"), ("p9004", "p9005"), ("p9006", "p9007"), ("p9009", "p9010")}


def fixture() -> ResearchCase:
    """The 400-person large fixture, each person with a given name of their own, and the planted pairs."""
    case = large_case()
    for n, record in enumerate(r for rows in case.record_sets.values() for r in rows if isinstance(r, Person)):
        record.names = [Name(f"Ad{chr(97 + n // 26)}{chr(97 + n % 26)} Fable", surname="Fable")]
    case.add_many(planted())
    return case


def config(**research) -> ProjectConfig:
    return ProjectConfig(name="Fictional duplicates", research=research, names={"variants": {"Fable": ["Fabel"]}})


def pairs(html: str) -> list[tuple[str, str]]:
    return [(a, b) for a, b in re.findall(r'href="(?:\.\./)?compare\.html\?a=([^&"]+)&amp;b=([^"]+)"', html)]


class DuplicatesPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.out = Path(cls.directory.name)
        case = fixture()
        assert PEOPLE == 400 and validate_case(case) == []
        build_site(case, config(duplicates=True), cls.out)
        cls.page = (cls.out / "duplicates.html").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_finds_the_planted_pairs_and_no_pair_with_different_given_names(self):
        self.assertEqual({frozenset(p) for p in EXPECTED}, {frozenset(p) for p in pairs(self.page)})
        self.assertEqual(len(EXPECTED), len(pairs(self.page)))
        self.assertIn("4 pairs, in surname and name order.", self.page)

    def test_rows_show_names_lifespans_places_and_a_compare_link(self):
        rows = re.findall(r"<tr>(.*?)</tr>", self.page.split("<tbody>")[1])
        # Surname first, then name: Ada, Mara, Tobin, Wren (Fabel counts as Fable).
        # Within a pair, by name, then the dated person first.
        self.assertEqual(["p9001", "p9009", "p9007", "p9004"], [pairs(r)[0][0] for r in rows])
        ada = unescape(rows[0])
        self.assertIn(">Ada Fable</a>", ada)
        self.assertIn(">ÁDA Fable</a>", ada)
        self.assertIn("b. 1801 · p9001", ada)
        self.assertIn("b. 1803 · p9002", ada)
        self.assertIn("<td>None in common</td>", ada)
        self.assertIn('aria-label="Compare Ada Fable (p9001) with ÁDA Fable (p9002)">Compare</a>', ada)
        tobin = unescape(rows[2])
        self.assertIn('<td><ul class="pills"><li>Town 0010, Shire 3, Inventia</li></ul></td>', tobin)
        self.assertIn("b. 1850 · p9007", tobin)
        for href in re.findall(r'href="(people/[^"]+)"', self.page):
            self.assertTrue((self.out / href).is_file(), href)

    def test_wording_offers_leads_never_merges(self):
        self.assertIn("<h1>Possible duplicates</h1>", self.page)
        self.assertIn(CAUTION, self.page)
        self.assertIn("leads for a researcher to check", self.page)
        self.assertNotRegex(self.page.split("<main", 1)[1], r"(?i)\b(?:should|can) be merged|\bmerge (?:these|them)|same person\b")
        self.assertIn('href="duplicates.html"', (self.out / "sitemap.html").read_text())
        self.assertIn('data-view="duplicates" href="duplicates.html" aria-current="page"', self.page)

    def test_a_withheld_person_is_in_no_output(self):
        for path in self.out.rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("SECRET", text, path)
                self.assertNotIn("p9099", text, path)

    def test_the_page_is_off_unless_switched_on_and_a_rebuild_removes_it(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            build_site(crowd(3), config(duplicates=True), out)
            self.assertTrue((out / "duplicates.html").is_file())
            build_site(crowd(3), config(), out)
            self.assertFalse((out / "duplicates.html").exists())
            self.assertNotIn("duplicates.html", (out / "index.html").read_text())
            self.assertNotIn("duplicates.html", (out / "data" / "routes.json").read_text())

    def test_the_setting_must_be_a_boolean(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "genealogy.toml"
            path.write_text("[project]\nname = 'Fictional'\n[research]\nduplicates = 'true'\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "research.duplicates must be a boolean"):
                ProjectConfig.load(path)
            path.write_text("[project]\nname = 'Fictional'\n[research]\nduplicates = true\n", encoding="utf-8")
            self.assertTrue(ProjectConfig.load(path).research["duplicates"])
        with tempfile.TemporaryDirectory() as temp, self.assertRaisesRegex(ValueError, "research.duplicates must be a boolean"):
            build_site(crowd(3), config(duplicates="yes"), Path(temp))


def crowd(people: int = 33) -> ResearchCase:
    """Thirty-three people of one name and year: 528 pairs, past the 500 listed."""
    case = ResearchCase("fictional-crowd", "Fictional crowd")
    case.add_many([r for n in range(people) for r in person(f"q{n:03d}", Name("Odo Quill", surname="Quill"), 1790)])
    return case


class LongListTests(unittest.TestCase):
    def test_lists_the_first_500_pairs_on_small_pages_and_says_how_many_were_found(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            build_site(crowd(), config(duplicates=True), out)
            first = (out / "duplicates.html").read_text(encoding="utf-8")
            self.assertIn("528 pairs were found; the first 500, in surname and name order, are listed.", first)
            listed = pairs(first)
            for n in range(2, 6):
                page = (out / f"duplicates/page-{n}.html").read_text(encoding="utf-8")
                self.assertIn(f"<h1>Possible duplicates, page {n} of 5</h1>", page)
                self.assertIn(CAUTION, page)
                listed += pairs(page)
            self.assertFalse((out / "duplicates/page-6.html").exists())
            self.assertEqual(500, len(listed))
            self.assertEqual(500, len(set(listed)))
            self.assertEqual(sorted(listed), listed)  # one name throughout, so name order is record-ID order
            for path in out.glob("duplicates*.html"):
                self.assertLess(path.stat().st_size, 100_000, path)
            for path in (out / "duplicates").glob("*.html"):
                self.assertLess(path.stat().st_size, 100_000, path)
            self.assertIn('<a href="../duplicates.html">Pairs 1–100</a>', (out / "duplicates/page-2.html").read_text(encoding="utf-8"))
            self.assertEqual([], check_site(out)["broken"])
            # Fewer pairs need fewer pages; the rebuild removes the rest.
            build_site(crowd(20), config(duplicates=True), out)
            self.assertTrue((out / "duplicates/page-2.html").is_file())
            self.assertFalse((out / "duplicates/page-3.html").exists())
            build_site(crowd(20), config(), out)
            self.assertFalse((out / "duplicates/page-2.html").exists())

    def test_no_pairs_says_so(self):
        with tempfile.TemporaryDirectory() as temp:
            build_site(crowd(1), config(duplicates=True), Path(temp))
            page = (Path(temp) / "duplicates.html").read_text(encoding="utf-8")
            self.assertIn("No possible duplicates were found among the public people.", page)
            self.assertNotIn("<table", page)


if __name__ == "__main__":
    unittest.main()
