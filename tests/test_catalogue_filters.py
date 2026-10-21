"""Catalogue research filters: the compact recorded sex in the shared data, from public, current claims only."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Claim, ClaimStatus, Event, LivingStatus as L, Name, Person,
                              Relationship)
from genealogy.site import build_site


def person(pid, name):
    return [Person(pid, names=[Name(name, surname="Fable")], living=L.DECEASED, event_ids=[f"{pid}-b"], sensitivity=A.PUBLIC),
            Event(f"{pid}-b", "birth", date="1801", participant_ids=[pid], sensitivity=A.PUBLIC)]


def filters_case():
    case = ResearchCase("fictional-filters", "Fictional filters")
    case.add_many([
        *person("p0001", "Ada Fable"), *person("p0002", "Bram Fable"), *person("p0003", "Cora Fable"),
        *person("p0004", "Dov Fable"), *person("p0005", "Esme Fable"), *person("p0006", "Finn Fable"),
        Claim("p0001-sex", "p0001", "sex", "Female", sensitivity=A.PUBLIC),
        Claim("p0002-sex", "p0002", "sex", " m ", sensitivity=A.PUBLIC),
        # Rejected: the next current claim, or none, is what the filter reads.
        Claim("p0003-sex-old", "p0003", "sex", "M", status=ClaimStatus.REJECTED, sensitivity=A.PUBLIC),
        Claim("p0003-sex", "p0003", "sex", "F", sensitivity=A.PUBLIC),
        Claim("p0004-sex", "p0004", "sex", "REJECTED-SEX-VALUE", status=ClaimStatus.REJECTED, sensitivity=A.PUBLIC),
        # A private claim about a public person: withheld, so nothing about it is published.
        Claim("p0005-sex", "p0005", "sex", "SECRET-SEX-VALUE", sensitivity=A.PRIVATE),
        Claim("p0006-sex", "p0006", "sex", "U", sensitivity=A.PUBLIC),
        Relationship("r-1", "p0002", "p0001", "parent", sensitivity=A.PUBLIC),
    ])
    return case


class CatalogueFilterDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.out = Path(cls.directory.name)
        case = filters_case()
        assert validate_case(case) == []
        build_site(case, ProjectConfig(name="Fictional filters"), cls.out)
        script = (cls.out / "data/site-data.js").read_text(encoding="utf-8")
        cls.data = json.loads(script.removeprefix("window.GENEALOGY_SITE_DATA=").removesuffix(";\n"))

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_each_person_carries_one_compact_recorded_sex(self):
        sex = {p["id"]: p.get("sex") for p in self.data["people"]}
        self.assertEqual({"p0001": "F", "p0002": "M", "p0003": "F", "p0004": None, "p0005": None, "p0006": "U"}, sex)

    def test_a_rejected_or_private_claim_gives_no_sex(self):
        people = {p["id"]: p for p in self.data["people"]}
        self.assertNotIn("sex", people["p0004"])
        self.assertNotIn("sex", people["p0005"])
        for path in self.out.rglob("*"):
            if path.is_file():
                self.assertNotIn("SECRET-SEX-VALUE", path.read_text(encoding="utf-8", errors="ignore"), path)


if __name__ == "__main__":
    unittest.main()
