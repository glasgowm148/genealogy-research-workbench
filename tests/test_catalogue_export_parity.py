"""Standalone catalogue parity with the public projection."""
import json
import unittest

from genealogy.catalogue import catalogue_data, render_catalogue_html


class CatalogueExportParityTests(unittest.TestCase):
    def setUp(self):
        self.project = {
            "project": {"title": "Fictional public register"},
            "people": [
                {"id": "p1", "name": "Ada Example", "living": "deceased", "sensitivity": "public"},
                {"id": "p2", "name": "Bram Example", "living": False, "sensitivity": "public"},
            ],
            "places": [{"id": "pl1", "name": "Fableton", "sensitivity": "public"}],
            "events": [
                {"id": "e1", "kind": "birth", "date": "1801-02-03", "place_id": "pl1", "participant_ids": ["p1"], "sensitivity": "public"},
                {"id": "e2", "kind": "death", "date": "1870", "participant_ids": ["p1"], "sensitivity": "public"},
            ],
            "relationships": [{"id": "r1", "subject_id": "p1", "object_id": "p2", "kind": "sibling", "sensitivity": "public"}],
            "claims": [{"id": "c1", "subject_id": "p1", "predicate": "occupation", "value": "keeper", "sensitivity": "public"}],
        }

    def test_data_has_life_facts_places_and_reciprocal_relatives(self):
        data = catalogue_data(self.project)
        people = {p["id"]: p for p in data["people"]}
        self.assertEqual({"p1", "p2"}, set(people))
        self.assertEqual("1801-02-03", people["p1"]["birth_date"])
        self.assertEqual("Fableton", people["p1"]["birth_place"])
        self.assertEqual("1870", people["p1"]["death_date"])
        self.assertEqual("Bram Example", people["p1"]["relatives"][0]["name"])
        self.assertEqual("Ada Example", people["p2"]["relatives"][0]["name"])

    def test_html_search_contains_new_facets(self):
        html = render_catalogue_html(self.project)
        self.assertIn("1801-02-03", html)
        self.assertIn("Fableton", html)
        self.assertIn("Bram Example", html)
        embedded = json.loads(html.split('<script id="catalogue-data" type="application/json">', 1)[1].split("</script>", 1)[0])
        self.assertEqual({"p1", "p2"}, {p["id"] for p in embedded["people"]})

    def test_person_event_references_also_supply_vital_facts(self):
        self.project["events"][0]["participant_ids"] = []
        self.project["people"][0]["event_ids"] = ["e1"]
        person = catalogue_data(self.project)["people"][0]
        self.assertEqual("1801-02-03", person["birth_date"])
        self.assertEqual("Fableton", person["birth_place"])

    def test_withheld_relatives_and_places_do_not_enter_catalogue_facets(self):
        from genealogy.case import ResearchCase
        from genealogy.config import ProjectConfig
        from genealogy.exports import project_for_public_export
        from genealogy.models import AccessLevel as A, Event, LivingStatus as L, Name, Person, Place, Relationship
        case = ResearchCase("fictional", "Fictional")
        case.add_many([
            Person("ada", names=[Name("Ada Fable")], living=L.DECEASED, sensitivity=A.PUBLIC),
            Person("hidden", names=[Name("WITHHELD-NAME")], living=L.LIVING, sensitivity=A.PUBLIC),
            Place("hidden-place", "WITHHELD-PLACE", sensitivity=A.PRIVATE),
            Event("hidden-birth", "birth", date="1801", participant_ids=["ada"], place_id="hidden-place", sensitivity=A.PUBLIC),
            Relationship("hidden-link", "ada", "hidden", "parent", sensitivity=A.PUBLIC),
        ])
        html = render_catalogue_html(project_for_public_export(case, ProjectConfig(name="Fictional")))
        self.assertIn("Ada Fable", html)
        for secret in ("WITHHELD-NAME", "WITHHELD-PLACE", "hidden-birth", "hidden-link"):
            self.assertNotIn(secret, html)


if __name__ == "__main__":
    unittest.main()
