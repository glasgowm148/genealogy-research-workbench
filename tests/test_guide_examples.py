"""The evidence guide says what each grade usually rests on and shows one public example."""
from __future__ import annotations

from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.labels import CONFIDENCE, CONFIDENCE_BASIS, guide_basis, guide_entries
from genealogy.models import (AccessLevel as A, Claim, ClaimStatus as S, Confidence as C, LivingStatus as L, Name, Person,
                              Relationship)
from genealogy.site import build_site
from genealogy.sitecheck import check_site

GRADES_TOML = '''
[grades.strongly_supported]
label = "Strongly supported"
meaning = "Several independent records agree, short of proof."
confidence = "probable"
basis = "two or more independent records that agree, with none in conflict."

[grades.uncertain]
label = "Uncertain"
meaning = "The records are too thin to weigh either way."
confidence = "possible"
'''


def config(directory: Path, extra: str = GRADES_TOML) -> ProjectConfig:
    path = directory / "genealogy.toml"
    path.write_text('[project]\nname = "Fictional guide"\n' + extra, encoding="utf-8")
    return ProjectConfig.load(path)


def person(pid, name, **extra):
    return Person(pid, names=[Name(name)], living=L.DECEASED, sensitivity=A.PUBLIC, **extra)


def case() -> ResearchCase:
    c = ResearchCase("fictional-guide", "Fictional guide examples")
    c.add_many([
        person("ada", "Ada Fable"), person("bram", "Bram Fable"), person("cara", "Cara Fable"), person("ella", "Ella Fable"),
        person("dan", "Dan Wick"), person("finn", "Finn Wick"), person("gwen", "Gwen Wick"), person("abe", "Abe Fable"),
        # Sorts first by name, but is withheld, and so is every link to him.
        Person("hidden", names=[Name("Abel SECRET-Hidden")], living=L.LIVING),
        *(Claim(f"{pid}-sex", pid, "sex", value, sensitivity=A.PUBLIC)
          for pid, value in (("ada", "F"), ("bram", "M"), ("ella", "F"), ("dan", "M"), ("gwen", "F"), ("abe", "M"))),
        Relationship("hidden-parent", "hidden", "bram", "parent", confidence=C.DOCUMENTED, sensitivity=A.PUBLIC),
        # Between two public people, but private itself.
        Relationship("abe-parent", "abe", "bram", "parent", confidence=C.DOCUMENTED, rationale="SECRET-reason"),
        Relationship("cara-parent", "cara", "bram", "parent", confidence=C.DOCUMENTED, sensitivity=A.PUBLIC),
        Relationship("ada-parent", "ada", "bram", "parent", confidence=C.DOCUMENTED, sensitivity=A.PUBLIC),
        Relationship("ada-spouse", "ada", "dan", "spouse", confidence=C.PROBABLE, grade="strongly_supported", estimate=70, sensitivity=A.PUBLIC),
        Relationship("cara-mother", "cara", "ella", "parent", confidence=C.POSSIBLE, grade="uncertain", sensitivity=A.PUBLIC),
        Relationship("dan-mother", "dan", "gwen", "parent", confidence=C.PROBABLE, sensitivity=A.PUBLIC),
        Relationship("dan-father", "dan", "finn", "parent", tree_status="uncertain", sensitivity=A.PUBLIC),
        Claim("ada-alias", "ada", "alias", "SECRET-alias", status=S.SUPPORTED),
        Claim("hidden-born", "hidden", "birth", "1980", status=S.REJECTED, sensitivity=A.PUBLIC),
        Claim("cara-born", "cara", "birth", "1855", status=S.SUPPORTED, sensitivity=A.PUBLIC),
        Claim("ada-born", "ada", "birth", "1850", status=S.SUPPORTED, sensitivity=A.PUBLIC),
        Claim("bram-born", "bram", "birth", "1820 or 1822", status=S.DISPUTED, sensitivity=A.PUBLIC),
    ])
    return c


class GuideExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        root = Path(cls.directory.name)
        cls.config = config(root)
        cls.out = root / "site"
        build_site(case(), cls.config, cls.out)
        cls.guide = (cls.out / "evidence.html").read_text()

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def entry(self, anchor: str) -> str:
        """The dt and its dd elements, up to the next entry or the end of the list."""
        start = self.guide.index(f'<dt id="{anchor}">')
        ends = [i for i in (self.guide.find("<dt ", start + 1), self.guide.find("</dl>", start)) if i > 0]
        return self.guide[start:min(ends)]

    def example(self, anchor: str) -> str | None:
        found = re.search(r'<dd class="guide-example">Example: (.*?)</dd>', self.entry(anchor))
        return found[1] if found else None

    def test_configuration_accepts_a_basis_and_rejects_a_bad_one(self):
        self.assertEqual("two or more independent records that agree, with none in conflict.", self.config.grades["strongly_supported"]["basis"])
        self.assertNotIn("basis", self.config.grades["uncertain"])
        self.assertEqual(self.config.grades, self.config.to_dict()["grades"])
        with tempfile.TemporaryDirectory() as directory:
            for bad in ('basis = ""', 'basis = "  "', "basis = 3", 'basis = ["a record"]'):
                with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "grades.strong.basis must be a non-empty string"):
                    config(Path(directory), f'[grades.strong]\nlabel="S"\nmeaning="M"\nconfidence="probable"\n{bad}\n')
            with self.assertRaisesRegex(ValueError, "unknown settings: bases"):
                config(Path(directory), '[grades.strong]\nlabel="S"\nmeaning="M"\nconfidence="probable"\nbases="R"\n')

    def test_labels_give_a_basis_for_each_standard_grade_and_a_project_grade_that_has_one(self):
        self.assertEqual(set(CONFIDENCE), set(CONFIDENCE_BASIS))
        self.assertIn("names both people and the relationship", guide_basis("confidence-documented"))
        self.assertEqual("two or more independent records that agree, with none in conflict.", guide_basis("grade-strongly_supported", self.config.grades))
        # A project grade without one does not borrow the standard grade's: it may be weighed differently.
        self.assertIsNone(guide_basis("grade-uncertain", self.config.grades))
        for anchor in ("confidence-tree-link", "status-supported", "quality-original", "grade-missing"):
            self.assertIsNone(guide_basis(anchor, self.config.grades), anchor)

    def test_the_guide_prints_the_basis_under_the_meaning(self):
        self.assertIn(f'<dt id="confidence-documented">Documented</dt><dd>{CONFIDENCE["documented"][1]}</dd>'
                      '<dd class="guide-basis">Usually rests on: a record that names both people and the relationship between them, or states the fact directly.</dd>',
                      self.guide)
        self.assertIn('Counted as probable wherever the site groups or colours by confidence.</dd>'
                      '<dd class="guide-basis">Usually rests on: two or more independent records that agree, with none in conflict.</dd>', self.guide)
        for anchor in ("confidence-probable", "confidence-possible", "confidence-disproved", "confidence-unknown"):
            self.assertIn('<dd class="guide-basis">Usually rests on: ', self.entry(anchor), anchor)
        for anchor in ("grade-uncertain", "confidence-tree-link", "status-supported", "quality-original"):
            self.assertNotIn("guide-basis", self.entry(anchor), anchor)

    def test_each_entry_shows_the_first_public_family_link_it_describes(self):
        ada = next(p for p in (self.out / "people").glob("*.html") if 'data-person-id="ada"' in p.read_text())
        to_ada = f'<a href="people/{ada.name}#family-heading">'
        self.assertEqual(to_ada + "Ada Fable and her father Bram Fable</a>", self.example("confidence-documented"))
        self.assertIn('<dd class="guide-example">Example: ' + to_ada + "Ada Fable and her father Bram Fable</a></dd>", self.guide)
        # A graded link is an example of its grade, and of the estimate it carries.
        self.assertEqual(to_ada + "Ada Fable and her spouse or partner Dan Wick</a>", self.example("grade-strongly_supported"))
        self.assertEqual(to_ada + "Ada Fable and her spouse or partner Dan Wick</a>", self.example("estimate"))
        self.assertIn(">Cara Fable and their mother Ella Fable</a>", self.example("grade-uncertain"))
        self.assertIn(">Dan Wick and his mother Gwen Wick</a>", self.example("confidence-probable"))
        self.assertIn(">Dan Wick and his parent Finn Wick</a>", self.example("confidence-tree-link"))
        self.assertIn(">Dan Wick and his parent Finn Wick</a>", self.example("tree-marked"))
        # Nothing on the site is disproved, possible without a grade, or unassessed rather than a tree link.
        for anchor in ("confidence-disproved", "confidence-possible", "confidence-unknown", "pedigree", "alternatives", "quality-original"):
            self.assertIsNone(self.example(anchor), anchor)
        # Every example lands on a page that has the family section.
        self.assertEqual([], check_site(self.out)["broken"])
        self.assertIn('id="family-heading"', ada.read_text())

    def test_each_claim_status_shows_the_first_public_claim(self):
        supported = self.example("status-supported")
        self.assertRegex(supported, r'^<a href="[^"]+#[^"]+">Ada Fable — birth: 1850</a>$')
        self.assertRegex(self.example("status-disputed"), r">Bram Fable — birth: 1820 or 1822</a>$")
        # The sex claims are asserted, but are never listed as claims; the rejected one is withheld.
        self.assertIsNone(self.example("status-asserted"))
        self.assertIsNone(self.example("status-rejected"))
        self.assertIsNone(self.example("status-open"))
        target, anchor = re.search(r'href="([^"#]+)#([^"]+)"', supported).groups()
        self.assertIn(f'id="{anchor}"', (self.out / target).read_text())

    def test_the_guide_keeps_its_anchors(self):
        anchors = [anchor for anchor, *_ in guide_entries(self.config.grades)]
        self.assertEqual(anchors, re.findall(r'<dt id="([^"]+)">', self.guide))

    def test_nothing_withheld_is_picked_or_printed(self):
        for name in ("Abel", "Abe Fable", "Hidden", "1980"):
            self.assertNotIn(name, self.guide)
        for path in self.out.rglob("*"):
            if path.is_file():
                self.assertNotIn("SECRET", path.read_text(errors="ignore"), path)

    def test_a_site_with_nothing_to_show_has_no_example_lines(self):
        c = ResearchCase("fictional-empty", "Fictional empty")
        c.add_many([person("ada", "Ada Fable"), Person("hidden", names=[Name("SECRET-Hidden")], living=L.LIVING),
                    Relationship("hidden-parent", "ada", "hidden", "parent", confidence=C.DOCUMENTED, sensitivity=A.PUBLIC)])
        self.assertEqual([], validate_case(c))
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "site"
            build_site(c, config(Path(directory), ""), out)
            guide = (out / "evidence.html").read_text()
            self.assertNotIn("guide-example", guide)
            self.assertNotIn("SECRET", guide)
            self.assertEqual(len(CONFIDENCE), guide.count('class="guide-basis"'))


if __name__ == "__main__":
    unittest.main()
