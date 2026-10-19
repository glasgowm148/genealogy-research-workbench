"""Synthetic regressions for user-supplied tree exports."""
import json
from pathlib import Path
import unittest

from genealogy.adapters import GedcomAdapter, OneTreeAdapter
from genealogy.adapters.base import AdapterBatch
from genealogy.case import ResearchCase, validate_case
from genealogy.models import Citation, Claim, Confidence, Event, Evidence, Person, Place, Relationship, Sensitivity, Source

FIXTURES = Path(__file__).parents[1] / "examples" / "imports"


class ImporterTests(unittest.TestCase):
    def assert_valid(self, batch):
        case = ResearchCase(id="fictional-import", title="Fictional import")
        batch.add_to_case(case)
        self.assertEqual(validate_case(case), [])
        return case

    def test_gedcom_unicode_event_citations_notes_and_coordinates(self):
        batch = GedcomAdapter().ingest((FIXTURES / "fictional-family.ged").read_bytes())
        case = self.assert_valid(batch)
        person = next(person for person in case.records(Person) if person.id.endswith("I1"))
        self.assertEqual([name.value for name in person.names], ["Élodie Fable", "Élodie Quill"])
        self.assertIn("multi-line. No historical", person.notes)
        events = {event.kind: event for event in case.records(Event) if person.id in event.participant_ids}
        self.assertTrue({"birth", "death", "burial", "residence", "occupation", "marriage"} <= events.keys())
        self.assertEqual(events["occupation"].description, "Bookbinder")
        birth = events["birth"]
        place = next(place for place in case.records(Place) if place.id == birth.place_id)
        self.assertEqual((place.latitude, place.longitude), (54.123, -4.321))
        citation = next(citation for citation in case.records(Citation) if citation.locator == "volume α, page 12")
        self.assertIn("\nThe spelling", citation.quotation)
        self.assertTrue(any(claim.subject_id == birth.id and citation.id in claim.citation_ids for claim in case.records(Claim)))
        self.assertTrue(all(claim.confidence == Confidence.UNKNOWN and claim.status.value == "asserted" for claim in case.records(Claim)))
        self.assertTrue(all(evidence.confidence == Confidence.UNKNOWN for evidence in case.records(Evidence)))
        self.assertTrue(all(item.sensitivity == Sensitivity.PRIVATE for item in batch.entities))
        protected = next(record for record in batch.records if record.external_id.value == "I3")
        self.assertEqual(protected.provenance["publishable_entity_ids"], [])
        family = next(record for record in batch.records if record.external_id.value == "F1")
        self.assertEqual(family.provenance["publishable_entity_ids"], [])
        self.assertIn("Volume α", case.records(Source)[0].title)
        self.assertEqual(case.records(Source)[0].repository, "Imaginary Municipal Archive")

    def test_gedcom_missing_endpoints_and_sources_are_omitted(self):
        batch = GedcomAdapter().ingest("0 @I1@ INDI\n1 NAME A /Fable/\n1 SOUR @S99@\n0 @F1@ FAM\n1 HUSB @I1@\n1 WIFE @I99@\n1 CHIL @I98@\n")
        self.assert_valid(batch)
        self.assertEqual(len(batch.warnings), 3)
        self.assertFalse(any(isinstance(item, Relationship) for item in batch.entities))
        self.assertFalse(any(isinstance(item, Citation) for item in batch.entities))

    def test_gedcom_repeated_events_and_inline_sources(self):
        batch = GedcomAdapter().ingest("0 @I1@ INDI\n1 NAME A /Fable/\n1 RESI\n2 DATE 1850\n2 SOUR Fictional census\n3 PAGE 12\n1 RESI\n2 DATE 1860\n1 DEAT N\n")
        case = self.assert_valid(batch)
        self.assertEqual(len(case.records(Event)), 2)
        self.assertEqual(len(case.records(Source)), 1)
        self.assertNotEqual(case.records(Person)[0].living, False)

    def test_gedcom_rejects_malformed_and_duplicate_records(self):
        for data in ("", "not gedcom", "0 HEAD\n0 TRLR", "0 @I1@ INDI\n3 NAME Wrong", "0 @I1@ INDI\n0 @I1@ INDI"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                GedcomAdapter().ingest(data)

    def test_onetree_actual_wrapper_names_coordinates_and_children(self):
        batch = OneTreeAdapter().ingest((FIXTURES / "fictional-onetree.json").read_text())
        case = self.assert_valid(batch)
        person = next(item for item in case.records(Person) if item.id.endswith("Fable-101"))
        self.assertEqual([name.value for name in person.names], ["Élodie Fable", "Élodie Quill"])
        self.assertIn("Synthetic biography", person.notes)
        self.assertTrue(any(identifier.value == "101" for identifier in person.external_ids))
        self.assertTrue(any(item.latitude == 54.123 for item in case.records(Place)))
        self.assertEqual(len(case.records(Person)), 3)
        self.assertTrue(any(item.kind == "spouse" and item.confidence == Confidence.POSSIBLE for item in case.records(Relationship)))
        self.assertTrue(any(item.kind == "parent" and item.subject_id.endswith("Example-103") and item.object_id.endswith("Quill-102") for item in case.records(Relationship)))
        living = next(item for item in case.records(Person) if item.id.endswith("Example-103"))
        self.assertEqual(living.living.value, "living")
        self.assertNotEqual(living.sensitivity, Sensitivity.PUBLIC)

    def test_onetree_dictionary_list_and_people_relationship_containers(self):
        profiles = {"p1": {"FirstName": "Fictional A", "DeathDate": "1900"}, "p2": {"FirstName": "Fictional B", "Father": "p1"}}
        for payload in (profiles, {"data": profiles}, [{"id": key, **row} for key, row in profiles.items()]):
            with self.subTest(payload=payload):
                case = self.assert_valid(OneTreeAdapter().ingest(payload))
                self.assertEqual(len(case.records(Person)), 2)
                self.assertEqual(len(case.records(Relationship)), 1)
        batch = OneTreeAdapter().ingest({"people": [{"id": "p1", "name": "Fictional A"}, {"id": "p2", "name": "Fictional B"}], "relationships": [{"id": "r1", "child_id": "p2", "parent_id": "p1", "kind": "parent", "confidence": "documented"}]})
        case = self.assert_valid(batch)
        self.assertEqual(case.records(Relationship)[0].confidence, Confidence.UNKNOWN)
        self.assertTrue(case.records(Relationship)[0].subject_id.endswith("p2"))

    def test_onetree_missing_relatives_never_create_people(self):
        batch = OneTreeAdapter().ingest({"data": {"p1": {"id": "p1", "Father": "missing", "Spouses": ["absent"]}}})
        case = self.assert_valid(batch)
        self.assertEqual(len(case.records(Person)), 1)
        self.assertFalse(case.records(Relationship))
        self.assertEqual(len(batch.warnings), 1)
        self.assertIn("2 relationships refer to 2 people not included in this export", batch.warnings[0])

    def test_onetree_rejects_invalid_json_and_rows(self):
        for payload in ("{broken", [], {"data": 2}, [None], {"people": [], "relationships": [{"id": "bad"}]}):
            with self.subTest(payload=payload), self.assertRaises((ValueError, TypeError)):
                OneTreeAdapter().ingest(payload)

    def test_invalid_coordinates_are_omitted_with_a_warning_never_kept_or_guessed(self):
        from genealogy.adapters._mapping import supplied_coordinates
        for coordinate in ("NaN", "Infinity", 100):
            with self.subTest(coordinate=coordinate):
                with self.assertRaises(ValueError):
                    supplied_coordinates(coordinate, 0)
                batch = OneTreeAdapter().ingest({"id": "fictional", "BirthLocation": "Imaginary", "BirthLatitude": coordinate})
                place = next(item for item in batch.entities if isinstance(item, Place))
                self.assertEqual((place.name, place.latitude, place.longitude), ("Imaginary", None, None))
                self.assertTrue(any("invalid supplied coordinates" in warning for warning in batch.warnings))
        gedcom = GedcomAdapter().ingest("0 @I1@ INDI\n1 BIRT\n2 PLAC Imaginary\n3 MAP\n4 LATI N95\n4 LONG W1\n")
        place = next(item for item in gedcom.entities if isinstance(item, Place))
        self.assertEqual((place.latitude, place.longitude), (None, None))
        self.assertTrue(any("invalid supplied coordinates" in warning for warning in gedcom.warnings))

    def test_batch_duplicate_index_preserves_conflict_checks(self):
        batch = AdapterBatch(adapter="fictional")
        for number in range(5000):
            batch.add_entity(Person(id=f"fictional:{number}"))
        batch.add_entity(Person(id="fictional:4"))
        self.assertEqual(len(batch.entities), 5000)
        with self.assertRaises(ValueError):
            batch.add_entity(Person(id="fictional:4", notes="conflicting observation"))

    def test_raw_dna_payloads_are_rejected_before_fields_are_dropped(self):
        for payload in ({"id": "fictional", "metadata": {"Genotypes": "A/G"}}, {"id": "fictional", "raw_dna": "ACGT"}):
            with self.subTest(payload=payload), self.assertRaisesRegex(ValueError, "raw DNA"):
                OneTreeAdapter().ingest(payload)
        with self.assertRaisesRegex(ValueError, "raw DNA"):
            GedcomAdapter().ingest("0 @I1@ INDI\n1 _RAW_DNA ACGT")

    def test_opaque_template_ids_are_not_genetic_field_names(self):
        payload = {"id": "fictional", "Templates": [{"params": {"VCF0-XYZ": "fictional link", "0XYZ-0VCF": "fictional link"}}]}
        self.assert_valid(OneTreeAdapter().ingest(payload))
        payload["Templates"][0]["params"]["VCF0-XYZ"] = {"genotypes": "A/G"}
        with self.assertRaisesRegex(ValueError, "raw DNA"):
            OneTreeAdapter().ingest(payload)

    def test_private_flag_cannot_be_overridden_by_provider_public(self):
        batch = OneTreeAdapter().ingest({"Name": "Fictional-1", "Privacy": 60, "private": True, "DeathDate": "1900"})
        self.assertEqual(batch.entities[0].sensitivity, Sensitivity.PRIVATE)
        self.assertEqual(batch.records[0].provenance["publishable_entity_ids"], [])

    def test_shared_places_respect_different_privacy_levels(self):
        batch = OneTreeAdapter().ingest([
            {"id": "p1", "BirthLocation": "Imaginary Place", "Privacy": 60},
            {"id": "p2", "BirthLocation": "Imaginary Place", "Privacy": 20},
            {"id": "p3", "BirthLocation": "Imaginary Place"},
        ])
        case = self.assert_valid(batch)
        self.assertEqual(len(case.records(Place)), 3)

    def test_death_placeholders_do_not_establish_deceased_status(self):
        for placeholder in ("unknown", "N/A", "0000", "0000-00-00", "not dead", "1900-02-30", "3000-01-01"):
            with self.subTest(placeholder=placeholder):
                batch = OneTreeAdapter().ingest({"id": "synthetic", "BirthDate": "2000", "DeathDate": placeholder})
                person = next(item for item in batch.entities if isinstance(item, Person))
                self.assertEqual(person.living.value, "unknown")
        for actual in ("1900", "1900-00-00", "1900-02", "1900-02-28", "28 FEB 1900", "FEB 1900", "ABT 1900"):
            with self.subTest(actual=actual):
                batch = OneTreeAdapter().ingest({"id": "synthetic", "DeathDate": actual})
                self.assertEqual(batch.entities[0].living.value, "deceased")
        explicit = OneTreeAdapter().ingest({"id": "synthetic", "DeathDate": "unknown", "living": False})
        self.assertEqual(explicit.entities[0].living.value, "deceased")

    def test_generic_display_names_are_not_person_ids(self):
        batch = OneTreeAdapter().ingest({"people": [
            {"id": "1", "name": "Fictional Smith"},
            {"id": "2", "name": "Fictional Smith", "Father": {"id": "1", "name": "Fictional Smith"}},
        ]})
        case = self.assert_valid(batch)
        self.assertEqual({person.id for person in case.records(Person)}, {"one-tree:person:1", "one-tree:person:2"})
        self.assertEqual(case.records(Relationship)[0].object_id, "one-tree:person:1")
        provider = OneTreeAdapter().ingest({"Id": 1, "Name": "Fictional-1"})
        self.assertEqual(provider.entities[0].id, "one-tree:person:Fictional-1")

    def test_place_case_variants_share_readable_label_and_keep_coordinate_distinctions(self):
        batch = GedcomAdapter().ingest("0 @I1@ INDI\n1 BIRT\n2 PLAC London\n0 @I2@ INDI\n1 BIRT\n2 PLAC LONDON")
        case = self.assert_valid(batch)
        self.assertEqual([place.name for place in case.records(Place)], ["London"])
        self.assertEqual(len({event.place_id for event in case.records(Event)}), 1)
        distinct = GedcomAdapter().ingest("0 @I1@ INDI\n1 BIRT\n2 PLAC London\n3 MAP\n4 LATI N50\n4 LONG E1\n0 @I2@ INDI\n1 BIRT\n2 PLAC LONDON\n3 MAP\n4 LATI N51\n4 LONG E1")
        self.assertEqual(len(self.assert_valid(distinct).records(Place)), 2)
        collision = AdapterBatch(adapter="synthetic")
        collision.add_entity(Place(id="same", name="London", latitude=50))
        with self.assertRaises(ValueError):
            collision.add_entity(Place(id="same", name="LONDON", latitude=51))
