"""The research progress page: assessed parent links, connected groups by grade, family heads and history."""
from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Confidence as C, Finding, LivingStatus as L, Name, Person, ResearchQuestion,
                              Relationship)
from genealogy.site import _owned, build_site

GRADES = {"strongly_supported": {"label": "Strongly supported", "meaning": "Several records agree.", "confidence": "probable"}}


def person(pid, name, sensitivity=A.PUBLIC):
    return Person(pid, names=[Name(name, surname=name.split()[-1])], living=L.DECEASED, sensitivity=sensitivity)


def parent(rid, child, of, confidence=C.UNKNOWN, **extra):
    return Relationship(rid, child, of, "parent", confidence=confidence, sensitivity=A.PUBLIC, **extra)


def finding(fid, on, changes=(), status="reviewed", sensitivity=A.PUBLIC):
    return Finding(fid, f"Conclusion {fid}.", recorded_on=on, status=status, sensitivity=sensitivity,
                   changes=[{"record_id": rid, "before": before, "after": after, "note": None} for rid, before, after in changes])


def case(findings=None, gwen=C.UNKNOWN):
    """Two families: the Fables (Ada heads three generations) and the Cairns (one unassessed link).

    Six of nine public people have a parent link; four of them an assessed one.
    """
    c = ResearchCase("fictional-progress", "Fictional progress")
    c.add_many([
        person("ada", "Ada Fable"), person("bram", "Bram Fable"), person("cara", "Cara Fable"), person("dora", "Dora Fable"),
        person("eli", "Eli Fable"), person("finn", "Finn Cairn"), person("gwen", "Gwen Cairn"), person("hal", "Hal Lone"),
        person("ivo", "Ivo Fable"),
        parent("bram-ada", "bram", "ada", C.DOCUMENTED),
        parent("cara-ada", "cara", "ada", C.PROBABLE, grade="strongly_supported"),
        parent("dora-bram", "dora", "bram", C.POSSIBLE),
        parent("eli-bram", "eli", "bram", C.DOCUMENTED),
        parent("gwen-finn", "gwen", "finn", gwen),
        # A disproved link: assessed, but it joins nothing and makes no one a parent.
        parent("ivo-hal", "ivo", "hal", C.DISPROVED),
        # Withheld: a private person and everything that depends on them.
        person("secret", "SECRET-PERSON-NAME", A.PRIVATE),
        parent("hal-secret", "hal", "secret", C.DOCUMENTED),
        ResearchQuestion("q-open", "Who were Ada's parents?", related_ids=["ada"], sensitivity=A.PUBLIC),
        ResearchQuestion("q-closed", "Was Bram baptised?", status="closed", sensitivity=A.PUBLIC),
        ResearchQuestion("q-secret", "SECRET-QUESTION-TEXT", related_ids=["secret"], sensitivity=A.PUBLIC),
        *(findings if findings is not None else [
            finding("f1", "2026-03-01", [("bram-ada", None, "documented")]),
            finding("f2", "2026-05-09", [("cara-ada", "possible", "strongly_supported")], status="draft"),
            finding("f3", "2026-06-01"),
            finding("f-secret", "2026-12-31", [("hal-secret", None, "documented")]),
            Finding("f-secret-text", "SECRET-FINDING-TEXT", recorded_on="2027-01-01", sensitivity=A.PRIVATE),
        ]),
    ])
    return c


def build(directory, c=None):
    build_site(c or case(), ProjectConfig(name="Fictional progress", grades=GRADES), directory)
    return (Path(directory) / "progress.html").read_text(encoding="utf-8")


def history(directory):
    path = Path(directory) / "data" / "progress-history.json"
    return json.loads(path.read_text(encoding="utf-8"))["snapshots"] if path.exists() else None


def section(html, anchor):
    start = html.index(f'id="{anchor}"')
    end = html.find("<h2", start)
    return html[start:end if end > 0 else len(html)]


def files(directory):
    return {p.relative_to(directory).as_posix(): p.read_bytes() for p in Path(directory).rglob("*") if p.is_file()}


class ProgressPageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.out = Path(self.temp.name) / "site"

    def tearDown(self):
        self.temp.cleanup()

    def test_measures_from_the_public_records(self):
        html = build(self.out)
        self.assertIn('href="progress.html" aria-current="page">Research progress</a>', html)
        self.assertTrue(_owned("progress.html") and _owned("data/progress-history.json"))
        # Bram, Cara, Dora, Eli and Ivo have assessed parent links (a disproved one counts as assessed);
        # Gwen's is an unassessed tree link. Nine public people.
        self.assertIn("<strong>55.6%</strong><small>people with an assessed parent link</small>", html)
        self.assertIn("5 of 9 people have at least one parent link", html)
        links = section(html, "parent-links")
        order = [re.sub(r"<[^>]+>", "", cell) for cell in re.findall(r'<th scope="row">(.*?)</th>', links)]
        self.assertEqual(["Documented", "Strongly supported", "Possible", "Unassessed tree link", "Disproved"], order)
        self.assertIn('href="evidence.html#grade-strongly_supported">Strongly supported</a></th><td>1</td><td>16.7%</td>', links)
        groups = section(html, "connected-groups")
        # The Fables hold together at worst Possible; the Cairns only by an unassessed link. Ivo and Hal are not joined.
        self.assertIn('<th scope="row">Group of 5 people around Ada Fable</th><td>5</td><td>4</td><td>Fable</td><td><a href="evidence.html#confidence-documented">Documented</a></td>'
                      '<td><a href="evidence.html#confidence-possible">Possible</a></td>', groups)
        self.assertIn('<th scope="row">Group of 2 people around Finn Cairn</th><td>2</td><td>1</td><td>Cairn</td>', groups)
        self.assertIn('Possible</a></th><td>1</td></tr><tr><th scope="row"><a href="evidence.html#confidence-tree-link">Unassessed tree link</a></th><td>1</td>', groups)
        heads = section(html, "family-heads")
        self.assertLess(heads.index(">Ada Fable</a>"), heads.index(">Finn Cairn</a>"))
        self.assertIn(">Ada Fable</a></th><td>2</td><td>4</td>", heads)
        self.assertRegex(heads, r'<a href="people/p-[0-9a-f]{64}\.html">Ada Fable</a>')
        self.assertNotIn("Hal Lone", heads)  # no children, and a disproved link makes no one a parent
        self.assertIn("2 people have neither a recorded parent nor recorded children.", heads)  # Hal and Ivo
        self.assertIn("<strong>1</strong><small>open questions</small>", html)
        self.assertIn("<strong>1</strong><small>draft findings</small>", html)
        recent = section(html, "recently-assessed")
        self.assertLess(recent.index("Conclusion f2."), recent.index("Conclusion f1."))
        self.assertNotIn("Conclusion f3.", recent)  # it changed no grade
        self.assertIn('<a class="badge evidence-badge badge-probable change" href="evidence.html#grade-strongly_supported" data-after="strongly_supported" data-before="possible">'
                      '<span class="badge-glyph" aria-hidden="true">~</span>Possible → Strongly supported</a>', recent)

    def test_recently_assessed_lists_the_newest_twenty(self):
        dated = [finding(f"f{n:02d}", f"2026-01-{n:02d}", [("bram-ada", None, "documented")] if n == 25 else [("eli-bram", None, "documented")])
                 for n in range(1, 26)]
        recent = section(build(self.out, case(dated)), "recently-assessed")
        self.assertEqual(20, recent.count("<li><p class=\"meta\">"))
        self.assertIn("Conclusion f25.", recent)
        self.assertNotIn("Conclusion f05.", recent)
        self.assertIn("Conclusion f06.", recent)

    def test_two_builds_write_identical_files(self):
        build(self.out)
        first = files(self.out)
        build(self.out)
        self.assertEqual(first, files(self.out))
        self.assertEqual(["2026-06-01"], [s["date"] for s in history(self.out)])

    def test_history_grows_only_when_the_newest_finding_date_changes(self):
        html = build(self.out)
        self.assertNotIn("<svg", html.split("<main", 1)[1])  # no chart; the shell's icons are outside main
        self.assertIn("One snapshot so far", html)
        # A change of grade without a newer finding updates that date's snapshot in place.
        build(self.out, case(gwen=C.PROBABLE))
        self.assertEqual([("2026-06-01", 6)], [(s["date"], s["with_assessed_parent"]) for s in history(self.out)])
        newer = case([finding("f1", "2026-03-01"), finding("f9", "2026-10-02", [("gwen-finn", "unknown", "probable")])], C.PROBABLE)
        html = build(self.out, newer)
        snapshots = history(self.out)
        self.assertEqual(["2026-06-01", "2026-10-02"], [s["date"] for s in snapshots])
        self.assertEqual({"date", "people", "with_assessed_parent", "parent_links", "assessed_parent_links", "connected_groups",
                          "family_heads", "open_questions", "draft_findings"}, set(snapshots[-1]))
        self.assertIn('<svg class="progress-chart"', html)
        self.assertIn('aria-label="Share of people with an assessed parent link over 2 snapshots, from 66.7% on 1 Jun 2026 to 66.7% on 2 Oct 2026"', html)
        self.assertIn('<th scope="row"><time datetime="2026-10-02">2 Oct 2026</time></th><td>9</td><td>6</td><td>66.7%</td>', html)  # the table alternative
        build(self.out, newer)
        self.assertEqual(2, len(history(self.out)))

    def test_history_keeps_sixty_snapshots_and_only_well_formed_counts(self):
        (self.out / "data").mkdir(parents=True)
        old = [{"date": f"2020-{1 + n // 28:02d}-{1 + n % 28:02d}", "people": 9, "with_assessed_parent": n % 9} for n in range(70)]
        old += [{"date": "<script>SECRET-DATE</script>", "people": 1, "with_assessed_parent": 1},
                {"date": "2021-01-01", "people": "nine", "with_assessed_parent": 1},
                {"date": "2021-02-02", "people": True, "with_assessed_parent": 1}]
        old[-4]["note"] = "SECRET-NOTE"
        (self.out / "data" / "progress-history.json").write_text(json.dumps({"snapshots": old}), encoding="utf-8")
        html = build(self.out)
        snapshots = history(self.out)
        self.assertEqual(60, len(snapshots))
        self.assertEqual("2026-06-01", snapshots[-1]["date"])
        self.assertEqual("2020-01-12", snapshots[0]["date"])
        text = (self.out / "data" / "progress-history.json").read_text(encoding="utf-8")
        for absent in ("SECRET", "2021-01-01", "2021-02-02"):
            self.assertNotIn(absent, text + html)

    def test_no_findings_no_snapshot_but_earlier_history_is_kept(self):
        html = build(self.out, case([]))
        self.assertIsNone(history(self.out))
        self.assertNotIn('id="history"', html)
        self.assertIn("No public finding has recorded a change of grade yet.", html)
        build(self.out)
        build(self.out, case([]))
        self.assertEqual(["2026-06-01"], [s["date"] for s in history(self.out)])

    def test_an_empty_project_says_so(self):
        html = build(self.out, ResearchCase("empty", "Empty"))
        self.assertIn("No public parent links recorded yet.", html)
        self.assertIn("No recorded relationships connect public people yet.", html)
        self.assertIn("<strong>—</strong><small>people with an assessed parent link</small>", html)

    def test_long_lists_are_capped(self):
        c = ResearchCase("fictional-many", "Fictional many families")
        for n in range(70):
            c.add_many([person(f"h{n:02d}", f"Head{n:02d} Fable"), person(f"k{n:02d}", f"Kid{n:02d} Fable"),
                        parent(f"k{n:02d}-h{n:02d}", f"k{n:02d}", f"h{n:02d}", C.POSSIBLE)])
        html = build(self.out, c)
        self.assertEqual(50, section(html, "family-heads").count("</th><td>1</td><td>1</td>"))
        self.assertIn("20 more family heads are not listed.", html)
        self.assertIn("10 smaller groups are not listed.", html)
        self.assertIn('<th scope="row"><a href="evidence.html#confidence-possible">Possible</a></th><td>70</td>', html)

    def test_withheld_records_reach_no_output(self):
        build(self.out)
        for name, content in files(self.out).items():
            for sentinel in (b"SECRET-", b"hal-secret", b"f-secret"):
                self.assertNotIn(sentinel, content, name)
        # The withheld finding is newer, but snapshots are dated from public findings only.
        self.assertEqual("2026-06-01", history(self.out)[-1]["date"])


if __name__ == "__main__":
    unittest.main()
