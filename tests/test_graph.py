import unittest

from genealogy import AccessLevel, Event, LivingStatus, Person, Relationship, ResearchCase
from genealogy.graph import RelationshipGraph


class RelationshipGraphTests(unittest.TestCase):
    def case(self) -> ResearchCase:
        case = ResearchCase(id="graph", title="Synthetic graph")
        for identifier in ("ancestor", "parent", "child", "partner"):
            case.add(Person(
                id=identifier, living=LivingStatus.DECEASED,
                sensitivity=AccessLevel.PUBLIC,
            ))
        case.add(Relationship(
            id="edge-1", subject_id="parent", object_id="ancestor", kind="parent",
        ))
        case.add(Relationship(
            id="edge-2", subject_id="child", object_id="parent", kind="parent",
        ))
        case.add(Relationship(
            id="edge-3", subject_id="parent", object_id="partner", kind="spouse",
        ))
        case.add(Event(
            id="event-1", kind="residence", date="1901", participant_ids=["child"],
        ))
        return case

    def test_family_traversal_and_events(self) -> None:
        graph = RelationshipGraph(self.case())
        self.assertEqual([person.id for person in graph.parents("child")], ["parent"])
        self.assertEqual([person.id for person in graph.children("parent")], ["child"])
        self.assertEqual([person.id for person in graph.partners("parent")], ["partner"])
        self.assertEqual(graph.ancestors("child")[1].person_ids, ("ancestor",))
        self.assertEqual(graph.descendants("ancestor")[1].person_ids, ("child",))
        self.assertEqual(graph.events_for("child")[0].id, "event-1")
        self.assertEqual(
            {person.id for person in graph.connected_component("child")},
            {"ancestor", "parent", "child", "partner"},
        )

    def test_depth_and_invalid_case_guards(self) -> None:
        graph = RelationshipGraph(self.case())
        self.assertEqual(len(graph.ancestors("child", max_depth=1)), 1)
        with self.assertRaisesRegex(ValueError, "max_depth"):
            graph.ancestors("child", max_depth=-1)
        broken = self.case()
        broken.records(Relationship)[0].object_id = "missing"
        with self.assertRaisesRegex(ValueError, "invalid research case"):
            RelationshipGraph(broken)


if __name__ == "__main__":
    unittest.main()
