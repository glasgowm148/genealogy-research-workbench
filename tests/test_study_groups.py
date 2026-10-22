"""A study records the groups it compares, how they connect and the records still to inspect."""
from __future__ import annotations

from html import unescape
from pathlib import Path
import re
import tempfile
import unittest

from genealogy.artifacts import build_case_artifact_bundle
from genealogy.case import ResearchCase, grade_errors, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Citation, Claim, Evidence, Event, LivingStatus as L, Name, Person, Source,
                              Study, record_from_dict)
from genealogy.site import build_site
from genealogy.sitecheck import check_site

GRADES = {"strongly_supported": {"label": "Strongly supported", "meaning": "Several records agree.", "confidence": "probable"}}
CAUTION = "Membership of a group records who the researcher is studying together; it does not by itself assert kinship."


def person(pid, name, born=None, sensitivity=A.PUBLIC, living=L.DECEASED):
    records = [Person(pid, names=[Name(name, surname=name.split()[-1])], living=living,
                      event_ids=[f"{pid}-b"] if born else [], sensitivity=sensitivity)]
    if born:
        records.append(Event(f"{pid}-b", "birth", date=born, participant_ids=[pid], sensitivity=sensitivity))
    return records


def groups():
    return [{"id": "mill", "title": "The Mill Lane household", "member_ids": ["ada", "bram"], "note": "One census schedule."},
            {"id": "quay", "title": "The Quay Street lodgers", "member_ids": ["cara", "dora"], "note": None},
            {"id": "chapel", "title": "Chapel baptisms", "member_ids": ["eli"]}]


def links():
    return [{"from": "mill", "to": "quay", "status": "strongly_supported", "note": "The same witness signs both entries.",
             "evidence_ids": ["ev-witness", "cite-register"]},
            {"from": "quay", "to": "chapel", "status": "possible", "note": None, "evidence_ids": []},
            {"from": "mill", "to": "chapel", "status": "disproved"}]


def study(**changes):
    values = dict(title="Households at the harbour", summary="Which household the children belong to.",
                  related_ids=["ada"], groups=groups(), links=links(),
                  next_records=["Inspect the original 1841 schedule for Quay Street.", "Search the chapel register for 1838–1845."],
                  updated_on="2026-10-01", sensitivity=A.PUBLIC)
    values.update(changes)
    return Study("s-harbour", **values)


def research_case(*extra, **study_changes):
    case = ResearchCase("fictional-groups", "Fictional groups")
    case.add_many([
        *person("ada", "Ada Fable", "1801"), *person("bram", "Bram Fable", "1830"), *person("cara", "Cara Vale", "1805"),
        *person("dora", "Dora Vale"), *person("eli", "Eli Marsh", "1840"),
        Source("register", "Invented harbour register", "register", sensitivity=A.PUBLIC),
        Citation("cite-register", "register", locator="entry 12", sensitivity=A.PUBLIC),
        Citation("cite-witness", "register", locator="entry 40", sensitivity=A.PUBLIC),
        Claim("ada-born", "ada", "birth", "1801", citation_ids=["cite-witness"], sensitivity=A.PUBLIC),
        Evidence("ev-witness", "ada-born", "cite-witness", "The witness is the same man.", sensitivity=A.PUBLIC),
        *extra, study(**study_changes),
    ])
    return case


class ValidationTests(unittest.TestCase):
    def test_a_complete_study_is_valid_and_round_trips(self):
        case = research_case()
        self.assertEqual([], validate_case(case) + grade_errors(case, GRADES))
        stored = case.records(Study)[0].to_dict()
        self.assertEqual(groups(), stored["groups"])
        again = record_from_dict("Study", stored)
        self.assertEqual(links(), again.links)
        self.assertEqual(stored["next_records"], again.next_records)
        self.assertEqual([], Study("s-plain", "No groups").groups)

    def test_malformed_groups_links_and_next_records_are_reported(self):
        bad_groups = [{"id": "mill", "title": "", "member_ids": ["ada", ""], "colour": "red"},
                      {"id": "mill", "title": "Again", "member_ids": [], "note": 3}, "not an object"]
        errors = "\n".join(validate_case(research_case(groups=bad_groups, links=[], next_records=["ok", ""])))
        for expected in ("s-harbour.groups must be a list of objects",):
            self.assertIn(expected, errors)
        errors = "\n".join(validate_case(research_case(groups=bad_groups[:2], links=[], next_records=["ok", ""])))
        for expected in ("s-harbour.groups[0] has unknown keys: colour", "s-harbour.groups[0].title must be a non-empty string",
                         "s-harbour.groups[0].member_ids must be a list of non-empty ids", "s-harbour.groups[1].id repeats group mill",
                         "s-harbour.groups[1].note must be a string or null", "s-harbour.next_records must be a list of non-empty strings"):
            self.assertIn(expected, errors)
        bad_links = [{"from": "mill", "to": "nowhere", "status": "possible"}, {"from": "mill", "to": "mill", "status": ""},
                     {"from": "quay", "to": "mill", "status": "possible", "evidence_ids": "ev-witness", "label": "x"}]
        errors = "\n".join(validate_case(research_case(links=bad_links)))
        for expected in ("s-harbour.links[0].to must name a group declared in s-harbour.groups: 'nowhere'",
                         "s-harbour.links[1] links group mill to itself", "s-harbour.links[1].status must be a confidence value or grade key",
                         "s-harbour.links[2] has unknown keys: label", "s-harbour.links[2].evidence_ids must be a list of non-empty ids"):
            self.assertIn(expected, errors)

    def test_members_must_be_people_and_evidence_must_be_evidence_or_citations(self):
        errors = validate_case(research_case(groups=[{"id": "mill", "title": "Mill", "member_ids": ["ada", "register", "ghost"]},
                                                     {"id": "quay", "title": "Quay", "member_ids": []}],
                                             links=[{"from": "mill", "to": "quay", "status": "possible", "evidence_ids": ["ada-born", "ev-witness"]}]))
        self.assertIn("s-harbour.groups[].member_ids must reference a Person: register", errors)
        self.assertIn("s-harbour.groups[].member_ids references missing record: ghost", errors)
        self.assertIn("s-harbour.links[].evidence_ids must reference a Evidence or Citation: ada-born", errors)
        self.assertEqual(3, len(errors))

    def test_link_status_must_be_a_confidence_value_or_a_defined_grade(self):
        case = research_case()
        self.assertIn("s-harbour.links[0].status is neither a confidence value nor a grade defined under [grades]: strongly_supported",
                      grade_errors(case, {}))
        self.assertEqual([], grade_errors(case, GRADES))


class StudyPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.paths = build_site(research_case(), ProjectConfig(name="Fictional", grades=GRADES), cls.root)
        cls.page = (cls.root / next(p for p in cls.paths if p.startswith("studies/s-"))).read_text()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def text(self, html):
        return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html)))

    def test_groups_list_their_members_with_lifespans_and_the_fixed_caution(self):
        text = self.text(self.page)
        self.assertIn(CAUTION, text)
        self.assertIn("The Mill Lane household One census schedule. Ada Fable b. 1801 Bram Fable b. 1830", text)
        self.assertIn("The Quay Street lodgers Cara Vale b. 1805 Dora Vale", text)
        self.assertEqual(3, self.page.count('class="study-group card"'))
        self.assertIn('href="../people/p-', re.search(r'<section class="study-group card".*?</section>', self.page).group(0))
        # Sections come in order before the conclusion, which precedes the study's linked records.
        order = [self.page.index(h) for h in ("<h2>Households and groups</h2>", "<h3>How the groups connect</h3>",
                                              "<h2>Records still to inspect</h2>", "<h2>Current conclusion</h2>", "<h2>People and records in this study</h2>")]
        self.assertEqual(sorted(order), order)

    def test_the_diagram_draws_boxes_and_labelled_lines_dashed_unless_documented_or_probable(self):
        svg = re.search(r'<svg class="groups-chart".*?</svg>', self.page).group(0)
        self.assertEqual(3, svg.count("<rect"))
        self.assertIn('aria-label="Diagram of 3 groups and 3 links between them"', svg)
        self.assertEqual(1, svg.count('class="link settled"'))
        self.assertEqual(1, svg.count('class="link open"'))
        self.assertEqual(1, svg.count('class="link open disproved"'))
        for label in ("Strongly supported", "Possible", "Disproved"):
            self.assertIn(f">{label}</text>", svg)
        self.assertIn("2 people</text>", svg)
        self.assertIn("1 person</text>", svg)
        anchor = re.search(r'<section class="study-group card" id="([^"]+)"', self.page).group(1)
        self.assertIn(f'<a href="#{anchor}">', svg)
        self.assertIn(".groups-chart .link.open{stroke:var(--gold-text);stroke-dasharray", next(self.root.rglob("site.css")).read_text())

    def test_a_text_alternative_lists_every_link_with_its_label_note_and_records(self):
        details = self.text(re.search(r'<details class="groups-text">.*?</details>', self.page).group(0))
        self.assertIn("Diagram of 3 groups and 3 links between them, as text", details)
        self.assertIn("The Mill Lane household → The Quay Street lodgers Strongly supported The same witness signs both entries. "
                      "Records: Invented harbour register (entry 40) , Invented harbour register (entry 12)", details)
        self.assertIn("The Quay Street lodgers → Chapel baptisms Possible", details)
        self.assertIn("The Mill Lane household → Chapel baptisms Disproved", details)
        self.assertIn('href="../evidence.html#grade-strongly_supported"', self.page)

    def test_records_still_to_inspect_are_listed_as_written(self):
        self.assertIn('<ul class="next-records"><li>Inspect the original 1841 schedule for Quay Street.</li>'
                      "<li>Search the chapel register for 1838–1845.</li></ul>", self.page)

    def test_a_grouped_person_links_back_to_the_study_and_links_resolve(self):
        dossier = next(p for p in (self.root / "people").glob("*.html") if 'data-person-id="eli"' in p.read_text()).read_text()
        self.assertIn("Households at the harbour", dossier)
        result = check_site(self.root)
        self.assertEqual([], result["broken"])
        self.assertEqual([], result["missing_anchors"])

    def test_a_study_without_groups_or_next_records_adds_no_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = build_site(research_case(groups=[], links=[], next_records=[]), ProjectConfig(name="Fictional"), Path(directory))
            page = (Path(directory) / next(p for p in paths if p.startswith("studies/s-"))).read_text()
        for absent in ("Households and groups", "groups-chart", "Records still to inspect", CAUTION):
            self.assertNotIn(absent, page)

    def test_groups_without_links_have_no_diagram(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = build_site(research_case(links=[]), ProjectConfig(name="Fictional"), Path(directory))
            page = (Path(directory) / next(p for p in paths if p.startswith("studies/s-"))).read_text()
        self.assertIn("<h2>Households and groups</h2>", page)
        self.assertNotIn("groups-chart", page)

    def test_only_the_first_twenty_groups_are_drawn(self):
        many = [{"id": f"g{n}", "title": f"Group {n}", "member_ids": ["ada"] if n % 2 else []} for n in range(25)]
        chain = [{"from": f"g{n}", "to": f"g{n + 1}", "status": "probable"} for n in range(24)]
        with tempfile.TemporaryDirectory() as directory:
            paths = build_site(research_case(groups=many, links=chain), ProjectConfig(name="Fictional"), Path(directory))
            page = (Path(directory) / next(p for p in paths if p.startswith("studies/s-"))).read_text()
        svg = re.search(r'<svg class="groups-chart".*?</svg>', page).group(0)
        self.assertEqual(20, svg.count("<rect"))
        self.assertEqual(19, svg.count('class="link settled"'))
        self.assertIn("5 more groups are listed above but not drawn", page)
        self.assertEqual(25, page.count('class="study-group card"'))
        self.assertEqual(24, re.search(r'<details class="groups-text">.*?</details>', page).group(0).count("<li>"))
        self.assertLess(len(svg), 12_000)


class PrivacyTests(unittest.TestCase):
    def build(self, case):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        build_site(case, ProjectConfig(name="Fictional", grades=GRADES), Path(directory.name))
        return "".join(p.read_text(errors="ignore") for p in Path(directory.name).rglob("*") if p.is_file())

    def test_a_study_grouping_a_withheld_person_is_withheld(self):
        secret = groups() + [{"id": "hidden", "title": "SECRET-GROUP-TITLE", "member_ids": ["living"], "note": "SECRET-GROUP-NOTE"}]
        everything = self.build(research_case(*person("living", "SECRET-LIVING Fable", "1990", living=L.LIVING),
                                              groups=secret, next_records=["SECRET-NEXT-RECORD"], title="SECRET-STUDY-TITLE"))
        for sentinel in ("SECRET-GROUP-TITLE", "SECRET-GROUP-NOTE", "SECRET-NEXT-RECORD", "SECRET-STUDY-TITLE", "SECRET-LIVING", "s-harbour"):
            self.assertNotIn(sentinel, everything)
        self.assertIn("Ada Fable", everything)  # the public people still publish

    def test_a_study_citing_withheld_evidence_for_a_link_is_withheld(self):
        hidden = Evidence("ev-hidden", "ada-born", "cite-register", "SECRET-ASSESSMENT", sensitivity=A.PRIVATE)
        secret_links = links() + [{"from": "quay", "to": "mill", "status": "possible", "note": "SECRET-LINK-NOTE", "evidence_ids": ["ev-hidden"]}]
        everything = self.build(research_case(hidden, links=secret_links))
        for sentinel in ("SECRET-LINK-NOTE", "SECRET-ASSESSMENT", "Households at the harbour"):
            self.assertNotIn(sentinel, everything)
        self.assertIn("Households at the harbour", self.build(research_case()))

    def test_bundles_follow_member_and_evidence_references(self):
        bundle = build_case_artifact_bundle(research_case())
        references = "\n".join(text for name, text in bundle.items() if "reference" in name or "graph" in name)
        self.assertIn("groups[].member_ids", references)
        self.assertIn("links[].evidence_ids", references)


if __name__ == "__main__":
    unittest.main()
