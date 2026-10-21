"""Recorded sibling links: the Family section, the evidence guide and the GEDCOM export."""
from __future__ import annotations

from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Claim, Confidence as C, Event, LivingStatus as L, Name, Person,
                              Relationship)
from genealogy.site import build_site
from genealogy.sitecheck import check_site


def person(pid, name, year, sex=None):
    records = [Person(pid, names=[Name(name, surname=name.split()[-1])], living=L.DECEASED, sensitivity=A.PUBLIC, event_ids=[f"{pid}-b"]),
               Event(f"{pid}-b", "birth", date=str(year), participant_ids=[pid], sensitivity=A.PUBLIC)]
    if sex:
        records.append(Claim(f"{pid}-sex", pid, "sex", sex, sensitivity=A.PUBLIC))
    return records


def sibling_case():
    case = ResearchCase("fictional-siblings", "Fictional siblings")
    records = [
        *person("p0001", "Ada Fable", 1800, "F"), *person("p0002", "Tobin Fable", 1770, "M"), *person("p0003", "Wren Fable", 1772, "F"),
        *person("p0004", "Iris Fable", 1802, "F"), *person("p0005", "Bram Fable", 1798, "M"), *person("p0006", "Nell Fable", 1805, "F"),
        *person("p0007", "Corin Vale", 1771, "M"), *person("p0008", "Pip Vale", 1804), *person("p0009", "Lark Vale", 1810),
        Relationship("r-af", "p0001", "p0002", "parent", confidence=C.DOCUMENTED, sensitivity=A.PUBLIC),
        Relationship("r-am", "p0001", "p0003", "parent", confidence=C.DOCUMENTED, sensitivity=A.PUBLIC),
        Relationship("r-if", "p0004", "p0002", "parent", sensitivity=A.PUBLIC),
        Relationship("r-im", "p0004", "p0003", "parent", sensitivity=A.PUBLIC),
        Relationship("r-pm", "p0008", "p0003", "parent", sensitivity=A.PUBLIC),
        Relationship("r-pf", "p0008", "p0007", "parent", sensitivity=A.PUBLIC),
        Claim("c-sib", "p0001", "sibling", "Iris Fable", sensitivity=A.PUBLIC),
        # (a) recorded, no parents in common; Ada is the object, so the link is read both ways
        Relationship("r-bram", "p0005", "p0001", "sibling", confidence=C.PROBABLE, sensitivity=A.PUBLIC),
        # (b) recorded and two parents in common, graded
        Relationship("r-iris", "p0001", "p0004", "sibling", confidence=C.DOCUMENTED, estimate=80, claim_ids=["c-sib"], sensitivity=A.PUBLIC),
        # (c) disproved
        Relationship("r-nell", "p0001", "p0006", "sister", confidence=C.DISPROVED, sensitivity=A.PUBLIC),
        # (d) half-siblings: by kind with the mother in common, and by pedigree alone
        Relationship("r-pip", "p0001", "p0008", "half_sibling", confidence=C.POSSIBLE, sensitivity=A.PUBLIC),
        Relationship("r-lark", "p0009", "p0001", "sibling", pedigree="half", sensitivity=A.PUBLIC),
    ]
    for record in records:
        case.add(record)
    return case


class RecordedSiblingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.paths = build_site(sibling_case(), ProjectConfig(name="Fictional siblings"), cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def dossier(self, name):
        return next(path for key, path in self.paths.items() if key.startswith("people/") and f"<h1>{name}</h1>" in path.read_text()).read_text()

    def siblings(self, name):
        section = self.dossier(name).split("<h3>Siblings</h3>", 1)[1].split("</section>", 1)[0]
        return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", item)).strip() for item in re.findall(r"<li>(.*?)</li>", section)]

    def test_fixture_is_valid(self):
        self.assertEqual([], validate_case(sibling_case()))

    def test_recorded_and_inferred_siblings_are_merged_in_birth_order(self):
        self.assertEqual([
            "Recorded sibling Bram Fable b. 1798 Probable",
            "Sibling (recorded link; two recorded parents in common) Iris Fable b. 1802 Documented (80%)",
            "Half-sibling (recorded link; shares a recorded parent) Pip Vale b. 1804 Possible",
            "Recorded half-sibling Lark Vale b. 1810 Unassessed tree link",
        ], self.siblings("Ada Fable"))

    def test_badges_link_to_the_guide_and_keep_stored_values(self):
        family = self.dossier("Ada Fable").split("<h3>Siblings</h3>", 1)[1].split("</section>", 1)[0]
        self.assertIn('href="../evidence.html#confidence-documented" data-confidence="documented"', family)
        self.assertIn('href="../evidence.html#confidence-tree-link"', family)

    def test_recorded_links_are_symmetric(self):
        self.assertEqual(["Recorded sibling Ada Fable b. 1800 Probable"], self.siblings("Bram Fable"))
        self.assertEqual(["Recorded half-sibling Ada Fable b. 1800 Unassessed tree link"], self.siblings("Lark Vale"))
        self.assertEqual(["Sibling (recorded link; two recorded parents in common) Ada Fable b. 1800 Documented (80%)",
                          "Shares a recorded parent Pip Vale b. 1804"], self.siblings("Iris Fable"))

    def test_disproved_link_is_not_a_sibling_but_stays_recorded(self):
        self.assertNotIn("Nell Fable", " ".join(self.siblings("Ada Fable")))
        self.assertEqual([], self.siblings("Nell Fable"))
        self.assertIn("No public siblings recorded.", self.dossier("Nell Fable"))
        for name in ("Ada Fable", "Nell Fable"):
            recorded = re.sub(r"<[^>]+>", " ", self.dossier(name).split("<h2>All recorded relationships</h2>", 1)[1])
            self.assertRegex(recorded, r"Ada Fable\s+— sister\s+→\s+Nell Fable\s+Disproved")

    def test_guide_explains_recorded_siblings_once(self):
        guide = self.paths["evidence.html"].read_text()
        self.assertEqual(1, guide.count(">Recorded sibling<"))
        roles = guide.split("Relationship roles", 1)[1]
        self.assertIn('id="recorded-sibling"', roles)

    def test_gedcom_has_no_sibling_family(self):
        text = self.paths["data/public-tree.ged"].read_text()
        # People are numbered in id order: p0001 is I1.
        families = [sorted(re.findall(r"^1 (HUSB|WIFE|CHIL) @I(\d)@", block, re.M)) for block in text.split(" FAM\n")[1:]]
        self.assertEqual([[("CHIL", "1"), ("CHIL", "4"), ("HUSB", "2"), ("WIFE", "3")],
                          [("CHIL", "8"), ("HUSB", "7"), ("WIFE", "3")]], families)
        for pointer in ("I5", "I6", "I9"):  # Bram, Nell and Lark are linked only as siblings
            self.assertNotRegex(text, rf"0 @{pointer}@ INDI\n(?:[1-9] .*\n)*?1 FAM[CS] ")

    def test_no_broken_links(self):
        self.assertEqual([], check_site(self.root)["broken"])


if __name__ == "__main__":
    unittest.main()
