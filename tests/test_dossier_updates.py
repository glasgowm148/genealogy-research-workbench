"""A dossier lists the changes still to make on the online tree: each pending relationship change, its finding and significance."""
from __future__ import annotations

import html
import json
from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Claim, ClaimStatus, Confidence as C, ExternalIdentifier, Finding, LivingStatus as L, Name,
                              Person, Relationship, record_from_dict)
from genealogy.site import PENDING_LIMIT, build_site


def change(record_id, before, after, note=None, significance=None):
    row = {"record_id": record_id, "before": before, "after": after, "note": note}
    return {**row, "significance": significance} if significance is not None else row


def person(pid, name, *, sensitivity=A.PUBLIC, external=()):
    return Person(pid, names=[Name(name, surname="Fable")], living=L.DECEASED, sensitivity=sensitivity, external_ids=list(external))


def sex(pid, value):
    return Claim(f"{pid}-sex", pid, "sex", value, status=ClaimStatus.SUPPORTED, confidence=C.DOCUMENTED, sensitivity=A.PUBLIC)


def updates_case(*, finding_status="draft", private_finding=False, private_other=False, extra=()):
    c = ResearchCase("fictional-updates", "Fictional updates")
    c.add_many([
        person("ada", "Ada Fable", external=[ExternalIdentifier("FableTree", "Fable-12", "https://tree.example.invalid/Fable-12"),
                                             ExternalIdentifier("FableTree", "Fable-13", "https://tree.example.invalid/Fable-13")]),
        person("bram", "Bram Fable"), person("cara", "Cara Fable"),
        person("hid", "SECRET-Person Fable", sensitivity=A.PRIVATE if private_other else A.PUBLIC),
        sex("bram", "M"), sex("ada", "F"),
        Relationship("ada-father", "ada", "bram", "parent", confidence=C.PROBABLE, sensitivity=A.PUBLIC),
        Relationship("ada-spouse", "ada", "cara", "spouse", confidence=C.POSSIBLE, sensitivity=A.PUBLIC),
        Relationship("ada-hid", "ada", "hid", "sibling", confidence=C.POSSIBLE, sensitivity=A.PUBLIC),
        Finding("f-father", "The baptism names Bram as Ada's father.", related_ids=["ada"], recorded_on="2026-09-08", status=finding_status,
                sensitivity=A.PUBLIC, changes=[change("ada-father", "possible", "probable", "Baptism entry found.", 55)]),
        Finding("f-spouse", "A marriage bond pairs Ada with Cara.", related_ids=["ada"], recorded_on="2026-10-01", status="draft",
                sensitivity=A.PRIVATE if private_finding else A.PUBLIC, changes=[change("ada-spouse", None, "possible", "SECRET-Finding note.")]),
        Finding("f-hid", "SECRET-Sibling finding.", related_ids=["ada"], recorded_on="2026-10-05", status="draft",
                sensitivity=A.PUBLIC, changes=[change("ada-hid", None, "possible")]),
        *extra,
    ])
    return c


def build(c, tree_name="FableTree"):
    temp = tempfile.TemporaryDirectory()
    config = ProjectConfig(name="Fictional updates", raw={"site": {"tree_name": tree_name}} if tree_name else {})
    config.validate()
    paths = build_site(c, config, Path(temp.name))
    return temp, paths


def dossier(paths, pid):
    return next(p.read_text() for key, p in paths.items() if key.startswith("people/") and f'data-person-id="{pid}"' in p.read_text())


def section(page):
    found = re.search(r'<h2 id="updates">.*?(?=<h2 id="relationships">)', page, re.S)
    return found.group(0) if found else ""


def text(fragment):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment))).strip()


class SignificanceTests(unittest.TestCase):
    def test_significance_is_optional_validated_and_round_trips(self):
        self.assertEqual([], validate_case(updates_case()))
        row = updates_case().records(Finding)[0]
        self.assertEqual(row, record_from_dict("Finding", json.loads(json.dumps(row.to_dict()))))
        self.assertEqual(55, row.to_dict()["changes"][0]["significance"])
        for value in (0, 100, None):
            with self.subTest(value=value):
                c = updates_case(extra=[Finding("f-x", "Fine.", sensitivity=A.PUBLIC, changes=[{**change("ada-spouse", None, "possible"), "significance": value}])])
                self.assertFalse([e for e in validate_case(c) if "significance" in e])
        for value in (-1, 101, 5.5, "55", True):
            with self.subTest(value=value):
                c = updates_case(extra=[Finding("f-x", "Bad.", sensitivity=A.PUBLIC, changes=[{**change("ada-spouse", None, "possible"), "significance": value}])])
                self.assertIn("f-x.changes[0].significance must be a whole number from 0 to 100, or null", validate_case(c))


class DossierUpdatesTests(unittest.TestCase):
    def test_section_lists_each_pending_change_with_its_finding(self):
        temp, paths = build(updates_case())
        self.addCleanup(temp.cleanup)
        page = dossier(paths, "ada")
        part = section(page)
        self.assertIn('<h2 id="updates">Pending FableTree updates</h2>', part)
        # After Research (and its log), before All relationships.
        self.assertLess(page.index('<h2 id="research-log">'), page.index('<h2 id="updates">'))
        items = re.findall(r"<li data-relationship-id=.*?</li>", part, re.S)
        self.assertEqual(3, len(items))
        # The most significant change first, then the newest finding.
        self.assertEqual(["ada-father", "ada-hid", "ada-spouse"], re.findall(r'data-relationship-id="([^"]+)"', part))
        father = text(items[0])
        self.assertIn("Father Bram Fable", father)
        self.assertIn("Possible → Probable", father)
        self.assertIn("Baptism entry found.", father)
        self.assertIn("Finding: The baptism names Bram as Ada's father. · 8 Sep 2026", father)
        self.assertIn("Significance 55 of 100", father)
        self.assertRegex(items[0], r'<a href="\.\./[^"]+">The baptism names Bram as Ada&#x27;s father\.</a>')
        self.assertIn('class="badge evidence-badge badge-', items[0])
        spouse = text(items[2])
        self.assertIn("Spouse or partner Cara Fable", spouse)
        self.assertIn("Recorded as Possible", spouse)
        self.assertNotIn("Significance", spouse)
        # The first external identifier with an address, marked as leaving the site.
        self.assertIn('<a href="https://tree.example.invalid/Fable-12" rel="noreferrer">Open on FableTree<span aria-hidden="true"> ↗</span></a>', part)
        self.assertNotIn("Fable-13", part)
        self.assertIn('<li><a href="#updates">Pending FableTree updates</a></li>', page)
        self.assertLess(page.index('href="#research"'), page.index('href="#updates"'))
        self.assertLess(page.index('href="#updates"'), page.index('href="#relationships"'))
        explore = re.search(r'<p class="explore">.*?</p>', page, re.S).group(0)
        self.assertRegex(explore, r'<a href="\.\./people/[^"#]+\.html#updates">Pending updates</a>')

    def test_the_other_end_reads_it_from_its_own_side(self):
        temp, paths = build(updates_case())
        self.addCleanup(temp.cleanup)
        part = section(dossier(paths, "bram"))
        self.assertIn("Daughter Ada Fable", text(part))
        self.assertIn("Significance 55 of 100", text(part))
        self.assertNotIn("Open on", part)  # Bram has no tree profile

    def test_reviewed_or_applied_changes_are_not_pending(self):
        for status in ("reviewed", "applied", "Applied"):
            with self.subTest(status=status):
                temp, paths = build(updates_case(finding_status=status))
                self.addCleanup(temp.cleanup)
                bram = dossier(paths, "bram")
                self.assertNotIn('id="updates"', bram)
                self.assertNotIn("#updates", bram)
                self.assertNotIn("Pending updates", bram)
                self.assertNotIn("ada-father", section(dossier(paths, "ada")))

    def test_without_a_tree_name(self):
        temp, paths = build(updates_case(), tree_name=None)
        self.addCleanup(temp.cleanup)
        page = dossier(paths, "ada")
        self.assertIn('<h2 id="updates">Pending tree updates</h2>', page)
        self.assertIn(">Open on FableTree<", page)  # the identifier's own system names the link
        self.assertIn('<a href="#updates">Pending tree updates</a>', page)

    def test_withheld_findings_and_people_are_never_listed(self):
        temp, paths = build(updates_case(private_finding=True, private_other=True))
        self.addCleanup(temp.cleanup)
        part = section(dossier(paths, "ada"))
        self.assertEqual(["ada-father"], re.findall(r'data-relationship-id="([^"]+)"', part))
        for path in paths.values():
            if path.is_file():
                body = path.read_bytes().decode("utf-8", "replace")
                with self.subTest(path=path.name):
                    self.assertNotIn("SECRET-", body)

    def test_nothing_pending_leaves_the_page_as_before(self):
        temp, paths = build(updates_case(finding_status="reviewed", private_finding=True, private_other=True))
        self.addCleanup(temp.cleanup)
        page = dossier(paths, "ada")
        self.assertNotIn('id="updates"', page)
        self.assertNotIn("Pending", page)

    def test_a_long_list_is_capped_and_counted(self):
        children = [person(f"kid{n:03d}", f"Kid {n:03d} Fable") for n in range(PENDING_LIMIT + 5)]
        links = [Relationship(f"kid{n:03d}-parent", f"kid{n:03d}", "bram", "parent", confidence=C.POSSIBLE, sensitivity=A.PUBLIC) for n in range(PENDING_LIMIT + 5)]
        found = Finding("f-kids", "The household return lists the children.", related_ids=["bram"], status="draft", sensitivity=A.PUBLIC,
                        changes=[change(f"kid{n:03d}-parent", None, "possible", significance=n) for n in range(PENDING_LIMIT + 5)])
        temp, paths = build(updates_case(extra=[*children, *links, found]))
        self.addCleanup(temp.cleanup)
        page = dossier(paths, "bram")
        part = section(page)
        self.assertEqual(PENDING_LIMIT, part.count("<li data-relationship-id="))
        self.assertIn("Significance 29 of 100", part)  # most significant first
        self.assertNotIn("Significance 4 of 100", part)
        self.assertIn('and 6 more, each noted beside its link under <a href="#relationships">All recorded relationships</a>', part)
        self.assertLess(len(page.encode()), 100_000)


if __name__ == "__main__":
    unittest.main()
