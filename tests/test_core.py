from pathlib import Path
import unittest

from genealogy import (
    AccessLevel, CaseStore, Citation, Claim, Evidence, ImportProvenance, LivingStatus,
    Person, PrivacyPolicy, ResearchCase, Source,
)
from genealogy.config import DEFAULT_PROJECT_NAME, ProjectConfig
from genealogy.case import validate_case
from genealogy.privacy import PrivacyViolation


class CoreTests(unittest.TestCase):
    def test_case_store_round_trip_and_public_projection(self) -> None:
        with self.subTest("durable round trip"), __import__("tempfile").TemporaryDirectory() as temp:
            case = ResearchCase(id="case-1", title="A fictional research case")
            person = Person(id="person-1", living=LivingStatus.DECEASED, sensitivity=AccessLevel.PUBLIC)
            source = Source(id="source-1", title="Open register", sensitivity=AccessLevel.PUBLIC)
            citation = Citation(id="citation-1", source_id=source.id, sensitivity=AccessLevel.PUBLIC)
            claim = Claim(id="claim-1", subject_id=person.id, predicate="birth_date", value="1870",
                          citation_ids=[citation.id], sensitivity=AccessLevel.PUBLIC)
            protected = Person(id="person-2", living=LivingStatus.UNKNOWN, sensitivity=AccessLevel.PUBLIC)
            for record in (person, source, citation, claim, protected):
                case.add(record)
            store = CaseStore(temp)
            store.save(case)
            projection = PrivacyPolicy().filter_public(store.load(case.id))
            self.assertEqual({entry["id"] for entry in projection["Person"]}, {"person-1"})
            self.assertEqual(projection["Claim"][0]["id"], "claim-1")


    def test_public_projection_removes_citation_without_public_source(self) -> None:
        case = ResearchCase(id="case-2", title="Safe links")
        source = Source(id="source-2", title="Restricted", sensitivity=AccessLevel.RESTRICTED)
        citation = Citation(id="citation-2", source_id=source.id, sensitivity=AccessLevel.PUBLIC)
        claim = Claim(id="claim-2", subject_id="person-1", predicate="note", value="x",
                      citation_ids=[citation.id], sensitivity=AccessLevel.PUBLIC)
        person = Person(id="person-1", living=False, sensitivity=AccessLevel.PUBLIC)
        for record in (person, source, citation, claim):
            case.add(record)
        projection = PrivacyPolicy().filter_public(case)
        self.assertNotIn("Citation", projection)
        self.assertNotIn("Claim", projection)

    def test_public_claim_cannot_disclose_an_unknown_living_person(self) -> None:
        case = ResearchCase(id="case-3", title="Living boundary")
        person = Person(id="person-3", living=LivingStatus.UNKNOWN, sensitivity=AccessLevel.PUBLIC)
        source = Source(id="source-3", title="Open source", sensitivity=AccessLevel.PUBLIC)
        citation = Citation(id="citation-3", source_id=source.id, sensitivity=AccessLevel.PUBLIC)
        claim = Claim(id="claim-3", subject_id=person.id, predicate="address", value="protected",
                      citation_ids=[citation.id], sensitivity=AccessLevel.PUBLIC)
        evidence = Evidence(id="evidence-3", claim_id=claim.id, citation_id=citation.id,
                            assessment="supports", sensitivity=AccessLevel.PUBLIC)
        for record in (person, source, citation, claim, evidence):
            case.add(record)
        projection = PrivacyPolicy().filter_public(case)
        self.assertNotIn("Claim", projection)
        self.assertNotIn("Evidence", projection)


    def test_config_preserves_consumer_extension_sections(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as temp:
            path = Path(temp) / "genealogy.toml"
            path.write_text("""[project]\nid = 'sample'\nname = 'Sample project'\n[research]\nmode = 'evidence'\n[consumer_extension]\ncolour = 'blue'\n""")
            config = ProjectConfig.load(path)
            self.assertEqual(config.project_id, "sample")
            self.assertEqual(config.to_dict()["consumer_extension"]["colour"], "blue")

    def test_living_and_access_permissions_are_cumulative(self) -> None:
        person = Person(id="person", living=LivingStatus.LIVING, sensitivity=AccessLevel.RESTRICTED)
        self.assertFalse(PrivacyPolicy(allow_restricted=True).permits(person))
        self.assertFalse(PrivacyPolicy(allow_living=True).permits(person))
        self.assertTrue(PrivacyPolicy(allow_living=True, allow_restricted=True).permits(person))
        with self.assertRaisesRegex(ValueError, "allow_living"):
            PrivacyPolicy(allow_living="false")  # type: ignore[arg-type]

    def test_raw_dna_is_rejected_at_add_load_and_save_boundaries(self) -> None:
        raw = Source(id="raw", title="Not portable", sensitivity=AccessLevel.RAW_DNA)
        with self.assertRaises(ValueError):
            ResearchCase(id="case", title="Case").add(raw)
        data = {"schema_version": 1, "id": "case", "title": "Case", "record_sets": {
            "Source": [{"id": "raw", "title": "Not portable", "sensitivity": "raw_dna"}],
        }}
        with self.assertRaises(ValueError):
            ResearchCase.from_dict(data)
        case = ResearchCase(id="case", title="Case", record_sets={"Source": [raw]})
        with self.assertRaises(ValueError):
            case.to_dict()
        with __import__("tempfile").TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                CaseStore(temp).save(case)
        with self.assertRaises(PrivacyViolation):
            PrivacyPolicy().filter_public(case)
        hidden = ImportProvenance(
            id="import", adapter="test", observations=[{"genotypes": "AA"}],
        )
        with self.assertRaisesRegex(ValueError, "raw DNA"):
            ResearchCase(id="case", title="Case").add(hidden)

    def test_duplicate_ids_and_numeric_living_values_fail_closed(self) -> None:
        case = ResearchCase(id="case", title="Case")
        case.add(Source(id="duplicate", title="Open", sensitivity=AccessLevel.PUBLIC))
        with self.assertRaisesRegex(ValueError, "duplicate record id"):
            case.add(Source(id="duplicate", title="Restricted", sensitivity=AccessLevel.RESTRICTED))
        malformed = ResearchCase(
            id="case", title="Case",
            record_sets={"Person": [Person(id="person", living=0, sensitivity=AccessLevel.PUBLIC)]},
        )
        self.assertTrue(any("living status" in error for error in validate_case(malformed)))
        with self.assertRaises(PrivacyViolation):
            PrivacyPolicy().filter_public(malformed)

    def test_schema_version_is_explicit_and_strict(self) -> None:
        case = ResearchCase(id="case", title="Case")
        self.assertEqual(1, case.to_dict()["schema_version"])
        with self.assertRaises(ValueError):
            ResearchCase.from_dict({"id": "case", "title": "Case", "record_sets": {}})
        with self.assertRaises(ValueError):
            ResearchCase.from_dict({"schema_version": True, "id": "case", "title": "Case", "record_sets": {}})

    def test_config_uses_literal_default_and_rejects_truthy_strings(self) -> None:
        self.assertEqual(DEFAULT_PROJECT_NAME, ProjectConfig.load(self._config("[project]\n")).name)
        with self.assertRaisesRegex(ValueError, "privacy.allow_living"):
            ProjectConfig.load(self._config("[privacy]\nallow_living = 'false'\n"))
        with self.assertRaisesRegex(ValueError, "catalogue.enabled"):
            ProjectConfig.load(self._config("[catalogue]\nenabled = 'true'\n"))

    def _config(self, content: str) -> Path:
        temp = __import__("tempfile").NamedTemporaryFile(mode="w", suffix=".toml", delete=False)
        self.addCleanup(lambda: Path(temp.name).unlink(missing_ok=True))
        temp.write(content)
        temp.close()
        return Path(temp.name)
