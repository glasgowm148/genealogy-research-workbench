"""The findings log as a filterable table: count, legend, feed link, study and place groups, and the findings index."""
from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import unittest

from genealogy.case import ResearchCase, validate_case
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Citation, Event, Finding, LivingStatus as L, Name, Person, Place, Source, Study)
from genealogy.site import FINDINGS_PER_PAGE, LATEST_FINDINGS, _anchor, build_site
from genealogy.sitecheck import check_site


def case(extra=(), *, many=0):
    c = ResearchCase("fictional-findings-table", "Fictional findings table")
    c.add_many([
        Person("ada", names=[Name("Ada Fable", surname="Fable")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Person("bram", names=[Name("Bram Fable", surname="Fable")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Person("secret", names=[Name("SECRET-LIVING person")], living=L.LIVING, sensitivity=A.PUBLIC),
        Place("lantern", "Lanternford (fictional)", sensitivity=A.PUBLIC),
        Place("willow", "Willowmere (fictional)", sensitivity=A.PUBLIC),
        Event("bram-b", "baptism", date="1802", place_id="willow", participant_ids=["bram"], sensitivity=A.PUBLIC),
        Source("register", "Invented parish register", "register", sensitivity=A.PUBLIC),
        Citation("register-1801", "register", locator="1801, entry 4", sensitivity=A.PUBLIC),
        Study("household", "The Fable household", summary="Who lived together.", related_ids=["ada"], status="reviewed", sensitivity=A.PUBLIC),
        Study("secret-study", "SECRET-STUDY title", related_ids=["ada"], sensitivity=A.PRIVATE),
        Finding("f-baptism", "Ada was baptised at Lanternford.", related_ids=["ada", "lantern"], status="reviewed", kind="vital",
                recorded_on="2026-10-02", limitations="The register is a later copy.", citation_ids=["register-1801"], evidence_ids=[],
                sensitivity=A.PUBLIC),
        Finding("f-brother", "Bram was baptised a year later.", related_ids=["bram", "bram-b"], status="draft", kind="record",
                recorded_on="2026-09-14", sensitivity=A.PUBLIC),
        Finding("f-undated", "The household moved once.", related_ids=["ada", "bram"], status="reviewed", sensitivity=A.PUBLIC),
        Finding("f-secret", "SECRET-FINDING about a living person.", related_ids=["secret"], recorded_on="2026-10-03", kind="SECRET-KIND",
                sensitivity=A.PUBLIC),
        *[Finding(f"f{n:03d}", f"Numbered conclusion {n}.", related_ids=["bram" if n % 2 else "ada"], status="final", kind="record",
                  recorded_on=f"2025-{1 + n // 28:02d}-{1 + n % 28:02d}", sensitivity=A.PUBLIC) for n in range(many)],
        *extra,
    ])
    return c


def build(c, directory, base_url="https://example.invalid/"):
    config = ProjectConfig(name="Fictional", raw={"site": {"base_url": base_url}} if base_url else {})
    build_site(c, config, Path(directory))
    return Path(directory)


def main(html):
    return html[html.index("<main"):html.index("</main>")]


class FindingsTableTests(unittest.TestCase):
    def test_the_log_is_a_five_column_table_with_count_legend_and_links(self):
        self.assertEqual([], validate_case(case()))
        with tempfile.TemporaryDirectory() as directory:
            out = build(case(), directory)
            log = main((out / "findings.html").read_text())
            heads = re.findall(r'<th scope="col">([^<]+)</th>', log)
            self.assertEqual(["Date", "Finding", "People", "Records", "Status and kind"], heads)
            self.assertEqual(3, log.count('class="finding-entry"'))
            row = log[log.index(f'id="{_anchor("f-baptism")}"'):]
            row = row[:row.index("</tr>")]
            for label in ("Date", "Finding", "People", "Records", "Status and kind"):
                self.assertIn(f'<td data-label="{label}"', row)
            self.assertIn('data-kind="vital"', row)
            self.assertIn('data-people="[&quot;ada&quot;]"', row)
            self.assertIn('data-places="[&quot;lantern&quot;]"', row)
            self.assertIn('data-studies="[&quot;household&quot;]"', row)  # the study concerns Ada
            # The details kept from the list: limits, cited records, type and status badges.
            self.assertIn("<strong>Limits:</strong> The register is a later copy.", row)
            self.assertIn("Invented parish register (1801, entry 4)", row)
            self.assertIn('data-kind="vital">Vital</a>', row)
            self.assertIn('href="evidence.html#confidence-unknown" data-status="reviewed" data-confidence="unknown"><span class="badge-glyph" aria-hidden="true">○</span>Reviewed · Unassessed</a>', row)
            # Brother's baptism event places that finding at Willowmere.
            self.assertIn('data-places="[&quot;willow&quot;]"', log[log.index(f'id="{_anchor("f-brother")}"'):])
            # Newest first, month groups as row headers, undated last.
            self.assertLess(log.index("October 2026"), log.index("September 2026"))
            self.assertLess(log.index("September 2026"), log.index("Undated findings"))
            self.assertIn('<th colspan="5" scope="rowgroup">October 2026</th>', log)
            self.assertIn('<p class="result-count">2 dated findings, and 1 undated.</p>', log)
            legend = log[log.index('class="findings-legend"'):log.index("</ul>", log.index('class="findings-legend"'))]
            for words in ('data-status="draft">Draft</a> A provisional conclusion', 'data-status="reviewed">Reviewed</a> A conclusion that has been checked',
                          'data-kind="record">Record</a>', 'data-kind="vital">Vital</a>'):
                self.assertIn(words, legend)
            self.assertIn('<a href="evidence.html">How to read the evidence</a>', log)
            # The feed, with its icon, and the quick links to the study and place groups.
            self.assertRegex(log, r'<p class="findings-links"><svg class="feed-icon"[^>]*aria-hidden="true".*?</svg><a href="findings.xml" type="application/atom\+xml">Follow new findings \(Atom feed\)</a>'
                                  r' · <a href="#by-study">Findings by study</a> · <a href="#by-place">Findings by place</a></p>')
            self.assertIn('<h2 id="by-study">Findings by study</h2>', log)
            self.assertIn('<a href="findings.html?study=household">The Fable household</a> <span class="meta">2 findings</span>', log)
            self.assertIn('<a href="findings.html?place=lantern">Lanternford (fictional)</a> <span class="meta">1 finding</span>', log)
            self.assertIn('<a href="findings.html?place=willow">Willowmere (fictional)</a> <span class="meta">1 finding</span>', log)
            self.assertEqual([], check_site(out)["broken"])
            # A short log needs no index: every finding is on the page.
            self.assertFalse((out / "data/findings-index.js").exists())

    def test_without_a_base_url_there_is_no_feed_link(self):
        with tempfile.TemporaryDirectory() as directory:
            out = build(case(), directory, base_url=None)
            log = (out / "findings.html").read_text()
            self.assertFalse((out / "findings.xml").exists())
            self.assertNotIn("findings.xml", log)
            self.assertNotIn("feed-icon", log)
            self.assertIn('<a href="#by-study">Findings by study</a>', log)

    def test_evidence_counts_are_worded_in_the_singular_and_plural(self):
        extra = [Finding("f-one", "One assessment.", related_ids=["ada"], evidence_ids=["e1"], recorded_on="2026-01-01", sensitivity=A.PUBLIC),
                 Finding("f-two", "Two assessments.", related_ids=["ada"], evidence_ids=["e1", "e2"], recorded_on="2026-01-02", sensitivity=A.PUBLIC)]
        from genealogy.models import Claim, Evidence
        records = [Claim("c1", "ada", "birth", "1801", sensitivity=A.PUBLIC),
                   Evidence("e1", "c1", "register-1801", "Entry 4.", sensitivity=A.PUBLIC), Evidence("e2", "c1", "register-1801", "Margin.", sensitivity=A.PUBLIC)]
        with tempfile.TemporaryDirectory() as directory:
            log = (build(case([*records, *extra]), directory) / "findings.html").read_text()
            self.assertIn(">1 evidence assessment</p>", log)
            self.assertIn(">2 evidence assessments</p>", log)
            self.assertNotIn("1 evidence assessments", log)

    def test_a_long_log_writes_an_index_and_archive_pages_share_the_table(self):
        with tempfile.TemporaryDirectory() as directory:
            out = build(case(many=120), directory)
            log = (out / "findings.html").read_text()
            self.assertEqual(LATEST_FINDINGS + 1, log.count('class="finding-entry"'))  # the newest, and the undated one
            self.assertIn('data-findings data-total="123" data-index="data/findings-index.js"', log)
            self.assertIn("The newest 30 of 122 dated findings, and 1 undated.", log)
            self.assertIn('<script defer src="data/site-data.js"></script>', log)  # person names for the filter
            first = (out / "findings/page-1.html").read_text()
            self.assertEqual(FINDINGS_PER_PAGE, first.count('class="finding-entry"'))
            self.assertIn('<th scope="col">Status and kind</th>', first)
            self.assertIn('<td data-label="Finding">', first)
            self.assertIn('href="../evidence.html#status-final" data-status="final">Final</a>', first)  # the legend
            self.assertNotIn("data-index", first)
            script = (out / "data/findings-index.js").read_text()
            self.assertTrue(script.startswith("window.GENEALOGY_FINDINGS=") and script.endswith(";\n"))
            index = json.loads(script[len("window.GENEALOGY_FINDINGS="):-2])
            self.assertEqual(123, len(index))
            self.assertEqual("f-baptism", index[0]["i"])
            self.assertEqual("f-undated", index[-1]["i"])
            baptism = index[0]
            self.assertEqual({"i": "f-baptism", "d": "2026-10-02", "c": "Ada was baptised at Lanternford.", "x": "The register is a later copy.",
                              "k": "vital", "s": "reviewed", "a": "confidence-unknown", "b": "Reviewed · Unassessed", "p": ["ada"], "t": ["household"],
                              "g": ["lantern"]}, {k: v for k, v in baptism.items() if k != "u"})
            # Each entry's address is where the page shows that finding, and resolves.
            for entry in index:
                path, _, anchor = entry["u"].partition("#")
                self.assertIn(f'id="{anchor}"', (out / path).read_text(), entry["i"])
            self.assertEqual([], check_site(out)["broken"])
            # Once the log is short again, the index is removed.
            out = build(case(many=10), directory)
            self.assertFalse((out / "data/findings-index.js").exists())

    def test_withheld_findings_and_studies_leave_no_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            out = build(case(many=40), directory)
            self.assertTrue((out / "data/findings-index.js").exists())
            for path in out.rglob("*"):
                if path.is_file():
                    text = path.read_text(errors="ignore")
                    for sentinel in ("SECRET-FINDING", "SECRET-KIND", "SECRET-STUDY", "SECRET-LIVING", "f-secret", "secret-study"):
                        self.assertNotIn(sentinel, text, f"{sentinel} in {path.relative_to(out)}")

    def test_an_empty_log_says_so_without_a_table(self):
        c = ResearchCase("empty", "Empty")
        c.add(Person("ada", names=[Name("Ada Fable")], living=L.DECEASED, sensitivity=A.PUBLIC))
        with tempfile.TemporaryDirectory() as directory:
            log = (build(c, directory) / "findings.html").read_text()
            self.assertIn("No public findings recorded yet.", log)
            self.assertNotIn("data-findings", log)
            self.assertNotIn("by-study", log)


if __name__ == "__main__":
    unittest.main()
