"""Dossier family structure, evidence labels, shared data and public downloads."""
from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import unittest

from genealogy.adapters import GedcomAdapter
from genealogy.case import ResearchCase
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Claim, Confidence, Event, LivingStatus as L, Name, Person, Place,
                              Relationship, Source)
from genealogy.site import build_site


def person(pid, name, surname=None, sex=None):
    records = [Person(pid, names=[Name(name, kind="birth", surname=surname)], living=L.DECEASED, sensitivity=A.PUBLIC, event_ids=[f"{pid}-b"]),
               Event(f"{pid}-b", "birth", date="ABT 1800" if pid == "child" else "1770", participant_ids=[pid], sensitivity=A.PUBLIC)]
    if sex:
        records.append(Claim(f"{pid}-sex", pid, "sex", sex, sensitivity=A.PUBLIC))
    return records


def family_case():
    case = ResearchCase("fictional-family", "Fictional family")
    records = [
        *person("father", "Tobin Fable", "Fable", "M"), *person("mother", "Wren Fable", "Fable", "F"),
        *person("step", "Corin Vale", "Vale", "M"), *person("rival", "Other Fable", "Fable", "M"),
        *person("child", "Ada Fable", "Fable", "F"), *person("sister", "Iris Fable", "Fable", "F"),
        *person("half", "Pip Vale", "Vale"),
        Place("chapel", "Invented Chapel", latitude=55.0, longitude=-4.0, sensitivity=A.PUBLIC),
        Event("wedding", "marriage", date="1795", place_id="chapel", participant_ids=["father", "mother"], sensitivity=A.PUBLIC),
        Relationship("r-couple", "father", "mother", "spouse", sensitivity=A.PUBLIC),
        Relationship("r-f", "child", "father", "parent", tree_status="uncertain", sensitivity=A.PUBLIC),
        Relationship("r-m", "child", "mother", "parent", confidence=Confidence.PROBABLE, pedigree="birth", sensitivity=A.PUBLIC),
        Relationship("r-step", "child", "step", "parent", pedigree="step", sensitivity=A.PUBLIC),
        Relationship("r-rival", "child", "rival", "parent", confidence=Confidence.POSSIBLE, sensitivity=A.PUBLIC),
        Relationship("r-sf", "sister", "father", "parent", sensitivity=A.PUBLIC),
        Relationship("r-sm", "sister", "mother", "parent", sensitivity=A.PUBLIC),
        Relationship("r-half", "half", "mother", "parent", sensitivity=A.PUBLIC),
        Source("register", "Invented register", author="Imaginary Clerk", publication="Nowhere Press", sensitivity=A.PUBLIC),
        # Withheld: must not appear anywhere, including the GEDCOM and data script.
        Person("living", names=[Name("SECRET LIVING")], living=L.LIVING, sensitivity=A.PUBLIC),
        Relationship("r-living", "living", "child", "parent", sensitivity=A.PUBLIC),
    ]
    for record in records:
        case.add(record)
    return case


class FamilySiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        config = ProjectConfig(name="Fictional family", raw={"site": {"base_url": "https://example.invalid/family/"}})
        cls.paths = build_site(family_case(), config, cls.root)
        cls.dossier = next(path for name, path in cls.paths.items() if name.startswith("people/") and "<h1>Ada Fable</h1>" in path.read_text()).read_text()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def family_section(self, heading):
        section = self.dossier.split(f"<h3>{heading}</h3>", 1)[1].split("<h3>", 1)[0].split("</section>", 1)[0]
        return re.sub(r"<[^>]+>", " ", section)

    def test_dossier_names_roles_and_keeps_each_label(self):
        parents = self.family_section("Parents")
        self.assertIn("Father", parents)
        self.assertIn("Mother", parents)
        self.assertIn("Step-father", parents)
        self.assertIn("Unassessed tree link · tree-marked uncertain", parents)
        self.assertIn("Probable", parents)
        self.assertIn("Possible", parents)
        self.assertIn("Competing parent records", parents)
        self.assertIn("b. c. 1800", self.dossier)
        siblings = self.family_section("Siblings")
        self.assertIn("Iris Fable", siblings)
        self.assertIn("Pip Vale", siblings)
        self.assertRegex(siblings, r"Shares a recorded parent\s+Pip Vale")
        mother = next(path for name, path in self.paths.items() if name.startswith("people/") and "<h1>Wren Fable</h1>" in path.read_text()).read_text()
        self.assertRegex(re.sub(r"<[^>]+>", " ", mother), r"Marriage:\s+1795\s+· Invented Chapel")
        self.assertIn("Daughter", re.sub(r"<[^>]+>", " ", mother))

    def test_evidence_guide_resolves_every_badge(self):
        guide = self.paths["evidence.html"].read_text()
        anchors = set(re.findall(r'id="([^"]+)"', guide))
        for path in self.paths.values():
            if path.suffix == ".html":
                for anchor in re.findall(r'evidence\.html#([^"]+)"', path.read_text()):
                    self.assertIn(anchor, anchors, path.name)

    def test_shared_data_script_downloads_and_sitemap_contain_only_public_records(self):
        everything = "\n".join(path.read_text() for path in self.root.rglob("*") if path.is_file())
        self.assertNotIn("SECRET LIVING", everything)
        self.assertNotIn('"id": "living"', self.paths["data/site-data.js"].read_text())
        catalogue = self.paths["catalogue.html"].read_text()
        self.assertNotIn('"people":', catalogue)
        self.assertIn('data-surname="Vale"', catalogue)
        sitemap = self.paths["sitemap.xml"].read_text()
        self.assertIn("<loc>https://example.invalid/family/evidence.html</loc>", sitemap)
        self.assertEqual(sitemap.count("<loc>"), len([name for name in self.paths if name.endswith(".html")]))
        self.assertIn('rel="canonical" href="https://example.invalid/family/index.html"', self.paths["index.html"].read_text())

    def test_public_gedcom_round_trips_people_roles_and_sources(self):
        text = self.paths["data/public-tree.ged"].read_text()
        batch = GedcomAdapter().ingest(text)
        people = [entity for entity in batch.entities if isinstance(entity, Person)]
        self.assertEqual(len(people), 7)
        self.assertEqual({name.surname for p in people for name in p.names}, {"Fable", "Vale"})
        parents = [entity for entity in batch.entities if isinstance(entity, Relationship) and entity.kind == "parent"]
        roles = {(entity.subject_id[-2:], entity.object_id[-2:]): entity.pedigree for entity in parents}
        self.assertEqual([value for value in roles.values() if value], ["step"])
        self.assertTrue(any(isinstance(entity, Event) and entity.kind == "marriage" and entity.date == "1795" for entity in batch.entities))
        self.assertIn("1 AUTH Imaginary Clerk", text)
        self.assertNotIn("SECRET", text)

    def test_invalid_base_url_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(ValueError, "base_url"):
            build_site(family_case(), ProjectConfig(raw={"site": {"base_url": "javascript:alert(1)"}}), Path(tmp))


if __name__ == "__main__":
    unittest.main()
