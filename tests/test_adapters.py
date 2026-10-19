import json
import tempfile
import unittest
from pathlib import Path

from genealogy.adapters import (
    ArchiveAdapter, DnaAdapter, FamilySearchAdapter, GedcomAdapter, OcrAdapter,
    OneTreeAdapter, SpreadsheetAdapter, TabularAdapter, WikiTreeAdapter,
    adapter_registry, collect_family_profile_names, extract_biography,
    hydrate_family_envelope, resolve_adapter, save_wikitree_family_case,
    normalise_familysearch_pid, normalise_wikitree_profile_id, wikitree_family_case,
)
from genealogy.case import ResearchCase, validate_case
from genealogy.models import Citation, Claim, Evidence, Event, ImportProvenance, LivingStatus, Person, Relationship, Source
from genealogy.privacy import PrivacyViolation


class AdapterTests(unittest.TestCase):
    def test_provider_identifier_normalisers_accept_generic_ids_and_urls(self) -> None:
        self.assertEqual(
            "Example_Person-42",
            normalise_wikitree_profile_id("https://www.wikitree.com/wiki/Example%20Person-42"),
        )
        self.assertEqual("9ABC-DEF", normalise_familysearch_pid(" 9abc-def "))
        with self.assertRaisesRegex(ValueError, "Example-123"):
            normalise_wikitree_profile_id("not-an-id")
        with self.assertRaisesRegex(ValueError, "not a WikiTree URL"):
            normalise_wikitree_profile_id("https://wikitree.com.example.invalid/wiki/Example-42")
        with self.assertRaisesRegex(ValueError, "9ABC-DEF"):
            normalise_familysearch_pid("not-a-pid")

    def test_gedcom_and_tabular_adapters_preserve_external_identity(self) -> None:
        gedcom = GedcomAdapter().ingest("0 @I1@ INDI\n1 NAME Example /Person/")
        self.assertEqual(gedcom.records[0].external_id.system, "gedcom")
        self.assertEqual(gedcom.records[0].raw[0], "0 @I1@ INDI")
        self.assertIsInstance(gedcom.entities[0], Person)
        rows = TabularAdapter().ingest("id,name\nr-1,Example\n")
        self.assertEqual(rows.records[0].external_id.value, "r-1")
        self.assertEqual(SpreadsheetAdapter().name, "spreadsheets")
        self.assertEqual(OcrAdapter().name, "ocr")
        self.assertEqual(OneTreeAdapter().name, "one-tree")

    def test_gedcom_resets_at_non_record_level_zero_and_shares_places(self) -> None:
        batch = GedcomAdapter().ingest(
            "0 HEAD\n1 SOUR Example\n0 @I1@ INDI\n1 NAME A /Example/\n1 BIRT\n2 PLAC Fable Quay\n"
            "0 @I2@ INDI\n1 NAME B /Example/\n1 BIRT\n2 PLAC Fable Quay\n0 TRLR\n"
        )
        self.assertEqual([record.external_id.value for record in batch.records], ["I1", "I2"])
        places = [entity for entity in batch.entities if entity.__class__.__name__ == "Place"]
        self.assertEqual(len(places), 1)

    def test_gedcom_maps_sources_citations_aliases_and_marriages(self) -> None:
        batch = GedcomAdapter().ingest(
            "0 @I1@ INDI\n1 NAME Elian /Marrow/\n1 NAME E. /Marrow/\n1 SEX X\n"
            "1 DEAT\n2 DATE 1910\n1 SOUR @S1@\n2 PAGE folio 4\n"
            "0 @I2@ INDI\n1 NAME Tessa /Vale/\n"
            "0 @F1@ FAM\n1 HUSB @I1@\n1 WIFE @I2@\n1 MARR\n2 DATE 1889\n2 PLAC North Quay\n"
            "0 @S1@ SOUR\n1 TITL Invented parish register\n0 TRLR\n"
        )
        person = next(entity for entity in batch.entities if isinstance(entity, Person) and entity.id.endswith("I1"))
        self.assertEqual([name.kind for name in person.names], ["birth", "alias"])
        self.assertEqual(person.living, LivingStatus.DECEASED)
        self.assertTrue(any(isinstance(entity, Source) for entity in batch.entities))
        self.assertTrue(any(isinstance(entity, Citation) for entity in batch.entities))
        self.assertTrue(any(isinstance(entity, Claim) and entity.predicate == "documented-in" for entity in batch.entities))
        marriage = next(entity for entity in batch.entities if isinstance(entity, Event) and entity.kind == "marriage")
        self.assertEqual(len(marriage.participant_ids), 2)
        case = ResearchCase(id="gedcom-case", title="Synthetic GEDCOM")
        self.assertGreater(batch.add_to_case(case), 0)
        self.assertEqual(validate_case(case), [])


    def test_dna_adapter_rejects_raw_material(self) -> None:
        with self.assertRaises(PrivacyViolation):
            DnaAdapter().ingest({"id": "kit-1", "raw_data": "ACGT"})

    def test_dna_rejects_nested_case_insensitive_raw_material(self) -> None:
        with self.assertRaises(PrivacyViolation):
            DnaAdapter().ingest({"id": "summary-1", "summary": {"Nested": {"GeNoTyPeS": "ACGT"}}})
        batch = DnaAdapter().ingest({"id": "summary-2", "summary": "derived match", "claim_id": "claim-1"})
        self.assertEqual(batch.entities, [])
        self.assertTrue(batch.warnings)
        evidence = DnaAdapter().ingest({"id": "summary-3", "summary": "derived match", "claim_id": "claim-1", "citation_id": "citation-1"})
        self.assertIsInstance(evidence.entities[0], Evidence)

    def test_service_adapters_map_common_constrained_fields(self) -> None:
        wiki = WikiTreeAdapter().ingest({
            "id": "42", "Name": "Mira-Quill-1", "FirstName": "Mira", "LastNameAtBirth": "Quill",
            "BirthDate": "1841-03-03", "BirthLocation": "Fable Quay", "Father": "Orin-Quill-1",
        })
        self.assertTrue(any(isinstance(entity, Event) and entity.kind == "birth" for entity in wiki.entities))
        self.assertTrue(any(isinstance(entity, Relationship) and entity.kind == "parent" for entity in wiki.entities))
        familysearch = FamilySearchAdapter().ingest({
            "id": "LX9-4Q2", "display": {"givenName": "Mira", "surname": "Quill"},
            "facts": [{"type": "http://gedcomx.org/Birth", "date": {"formal": "+1841-03-03"}, "place": {"original": "Fable Quay"}}],
            "parents": ["ORIN-1"],
        })
        self.assertTrue(any(isinstance(entity, Person) for entity in familysearch.entities))
        self.assertTrue(any(isinstance(entity, Event) and entity.kind == "birth" for entity in familysearch.entities))
        identified_places = FamilySearchAdapter().ingest([
            {
                "id": "ONE-1", "display": {"name": "One"},
                "facts": [{"type": "Birth", "place": {"id": "P1", "original": "Springfield"}}],
            },
            {
                "id": "TWO-2", "display": {"name": "Two"},
                "facts": [{"type": "Birth", "place": {"id": "P2", "original": "Springfield"}}],
            },
        ])
        places = [entity for entity in identified_places.entities if entity.__class__.__name__ == "Place"]
        self.assertEqual({place.id for place in places}, {"familysearch:place:P1", "familysearch:place:P2"})
        one_tree = OneTreeAdapter().ingest({"id": "edge-1", "subject_id": "P-1", "object_id": "P-2", "relationship": "parent"})
        self.assertIsInstance(one_tree.entities[0], Relationship)

    def test_onetree_profile_wrapper_prefers_name_and_resolves_numeric_parents(self) -> None:
        batch = OneTreeAdapter().ingest({"data": {
            "first": {"Id": 101, "Name": "Mira-Quill-1", "DeathDate": "1908-10-12", "Privacy": 50, "Father": 102},
            "second": {"Id": 102, "Name": "Orin-Quill-1", "Privacy": 50},
        }})
        people = [entity for entity in batch.entities if isinstance(entity, Person)]
        mira = next(person for person in people if person.id.endswith("Mira-Quill-1"))
        self.assertEqual(mira.living.value, "deceased")
        parent = next(entity for entity in batch.entities if isinstance(entity, Relationship))
        self.assertTrue(parent.object_id.endswith("Orin-Quill-1"))

    def test_provider_privacy_and_wikitree_envelopes_are_normalised(self) -> None:
        batch = WikiTreeAdapter().ingest({"items": {
            "open": {"Id": 1, "Name": "Mira-Quill-1", "Privacy": 60, "DeathDate": "1908"},
            "closed": {"Id": 2, "Name": "Orin-Quill-1", "Privacy": 40, "DeathDate": "1880"},
        }})
        people = {person.external_ids[0].value: person for person in batch.entities if isinstance(person, Person)}
        self.assertEqual(people["Mira-Quill-1"].sensitivity.value, "public")
        self.assertEqual(people["Mira-Quill-1"].living.value, "deceased")
        self.assertEqual(people["Orin-Quill-1"].sensitivity.value, "restricted")
        raw = OneTreeAdapter().ingest({
            "Name": "Protected-1", "sensitivity": "raw_dna", "DeathDate": "1900",
        })
        self.assertEqual(next(entity for entity in raw.entities if isinstance(entity, Person)).sensitivity.value, "raw_dna")
        restricted = OneTreeAdapter().ingest({
            "Name": "Protected-2", "sensitivity": "public", "Privacy": 40, "DeathDate": "1900",
        })
        self.assertEqual(next(entity for entity in restricted.entities if isinstance(entity, Person)).sensitivity.value, "restricted")
        relatives = WikiTreeAdapter().ingest({"items": [{"person": {
            "Name": "Aster-Reed-1", "Privacy": 60, "DeathDate": "1900",
            "Children": {"2": {"Name": "Briar-Reed-2", "Privacy": 60, "DeathDate": "1930"}},
        }}]})
        self.assertEqual(len([entity for entity in relatives.entities if isinstance(entity, Person)]), 2)
        self.assertTrue(any(
            isinstance(entity, Relationship) and entity.kind == "parent"
            for entity in relatives.entities
        ))

    def test_wikitree_family_hydration_utilities_are_adapter_owned(self) -> None:
        envelope = {"items": [{"person": {
            "Name": "Aster-Reed-1",
            "Children": {"2": {"Name": "Briar-Reed-2", "marriage_date": "1888"}},
        }}]}
        self.assertEqual(
            collect_family_profile_names(envelope, "Aster-Reed-1"),
            ["Aster-Reed-1", "Briar-Reed-2"],
        )
        hydrated = hydrate_family_envelope(
            envelope,
            {
                "Aster-Reed-1": {"Name": "Aster-Reed-1", "Bio": "Subject biography"},
                "Briar-Reed-2": {"Name": "Briar-Reed-2", "Bio": {"wiki": "Child biography"}},
            },
            "Aster-Reed-1",
        )
        child = hydrated["items"][0]["person"]["Children"]["2"]
        self.assertEqual(child["marriage_date"], "1888")
        self.assertEqual(extract_biography(child), "Child biography")

    def test_wikitree_family_case_omits_uncaptured_relationship_endpoints(self) -> None:
        payload = {"items": [{"person": {
            "Name": "Aster-Reed-1", "DeathDate": "1900", "Father": "Unseen-Reed-1",
            "Children": {"2": {
                "Name": "Briar-Reed-2", "DeathDate": "1930", "Father": "Aster-Reed-1",
            }},
        }}]}
        case = wikitree_family_case(
            payload, case_id="family-capture", title="Synthetic family capture",
        )
        people = {person.id for person in case.records(Person)}
        relationships = case.records(Relationship)
        self.assertEqual(len(people), 2)
        self.assertTrue(relationships)
        self.assertTrue(all(
            relationship.subject_id in people and relationship.object_id in people
            for relationship in relationships
        ))
        with self.assertRaisesRegex(ValueError, "contains no people"):
            wikitree_family_case({"items": []}, case_id="empty")

        with tempfile.TemporaryDirectory() as temporary:
            path = save_wikitree_family_case(
                payload, temporary, case_id="family-capture",
            )
            saved = ResearchCase.from_dict(json.loads(path.read_text()))
        self.assertEqual(saved.id, "family-capture")

    def test_registry_and_fictional_source_to_case_flow(self) -> None:
        root = Path(__file__).parents[1] / "examples" / "fictional-harbour" / "input"
        gedcom = resolve_adapter({"adapter": "gedcom"}).ingest((root / "harbour-family.ged").read_text())
        archive = ArchiveAdapter().ingest([{"id": "ledger-1841", "entity_type": "source", "title": "Invented Fable Quay harbour ledger"}])
        tabular = resolve_adapter("tabular").ingest((root / "harbour-index.csv").read_text())
        case = ResearchCase(id="adapter-fixture", title="Adapter fixture")
        self.assertGreater(gedcom.add_to_case(case), 0)
        self.assertGreater(archive.add_to_case(case), 0)
        self.assertGreater(tabular.add_to_case(case), 0)
        self.assertTrue(case.records(Person))
        self.assertTrue(case.records(Source))
        self.assertEqual(len(case.records(ImportProvenance)), 3)
        self.assertNotIn("gedcom_lines", case.records(ImportProvenance)[0].observations[0])
        archive_url = ArchiveAdapter().ingest([{
            "id": "catalogue-1", "title": "Invented catalogue", "url": "https://example.invalid/item/1",
        }])
        source = next(entity for entity in archive_url.entities if isinstance(entity, Source))
        self.assertEqual(source.url, "https://example.invalid/item/1")
        licensed = ArchiveAdapter().ingest([{
            "id": "licensed-1", "title": "Licensed catalogue", "sensitivity": "public",
            "licensed_source": True,
        }])
        protected_source = next(entity for entity in licensed.entities if isinstance(entity, Source))
        self.assertEqual(protected_source.sensitivity.value, "licensed")
        self.assertIn("gedcom", adapter_registry())
        self.assertEqual(resolve_adapter("one_tree").name, "one-tree")
        with self.assertRaises(ValueError):
            resolve_adapter("not-a-real-adapter")

    def test_add_to_case_is_preflighted(self) -> None:
        batch = TabularAdapter().ingest("id,entity_type,name\np-1,person,Example Person\n")
        case = ResearchCase(id="safe-import", title="Safe import")
        batch.add_to_case(case)
        self.assertEqual(batch.add_to_case(case), 0)
        self.assertEqual(len(case.records(Person)), 1)

        conflicting = TabularAdapter().ingest(
            "id,entity_type,name\np-1,person,Different Person\n"
        )
        with self.assertRaises(ValueError):
            conflicting.add_to_case(case)
        self.assertEqual(len(case.records(Person)), 1)
