"""A project's own confidence grades, mapped onto the standard ones."""
from __future__ import annotations

import io
import json
from contextlib import redirect_stderr
from pathlib import Path
import tempfile
import unittest

from genealogy.case import ResearchCase, grade_errors, validate_case
from genealogy.cli import main
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Claim, ClaimStatus, Confidence as C, LivingStatus as L, Name, Person,
                              Relationship, record_from_dict)
from genealogy.site import build_site

GRADES_TOML = '''
[grades.strongly_supported]
label = "Strongly supported"
meaning = "Several independent records agree, short of proof."
confidence = "probable"

[grades.uncertain]
label = "Uncertain"
meaning = "The records are too thin to weigh either way."
confidence = "possible"
'''


def config(directory: Path, extra: str = GRADES_TOML) -> ProjectConfig:
    path = directory / "genealogy.toml"
    path.write_text('[project]\nname = "Fictional graded tree"\n' + extra, encoding="utf-8")
    return ProjectConfig.load(path)


def case(grade: str | None = "strongly_supported", confidence: C = C.PROBABLE) -> ResearchCase:
    c = ResearchCase("fictional-grades", "Fictional grades")
    c.add_many([
        Person("ada", names=[Name("Ada Fable")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Person("bram", names=[Name("Bram Fable")], living=L.DECEASED, sensitivity=A.PUBLIC),
        Relationship("ada-parent", "ada", "bram", "parent", confidence=confidence, grade=grade, estimate=80, sensitivity=A.PUBLIC),
        Claim("ada-born", "ada", "birth", "1801", status=ClaimStatus.SUPPORTED, confidence=C.POSSIBLE, grade="uncertain" if grade else None,
              sensitivity=A.PUBLIC),
    ])
    return c


class GradeTests(unittest.TestCase):
    def test_configuration_keeps_grades_in_order_and_rejects_bad_ones(self):
        with tempfile.TemporaryDirectory() as directory:
            loaded = config(Path(directory))
            self.assertEqual(["strongly_supported", "uncertain"], list(loaded.grades))
            self.assertEqual("probable", loaded.grades["strongly_supported"]["confidence"])
            self.assertEqual(loaded.grades, loaded.to_dict()["grades"])
            for bad, message in (('[grades.Strong]\nlabel="S"\nmeaning="M"\nconfidence="probable"\n', "grade key"),
                                 ('[grades.strong]\nlabel="S"\nmeaning="M"\nconfidence="likely"\n', "confidence must be one of"),
                                 ('[grades.strong]\nmeaning="M"\nconfidence="probable"\n', "label must be a non-empty string"),
                                 ('[grades.strong]\nlabel="S"\nmeaning="M"\nconfidence="probable"\ncolour="red"\n', "unknown settings: colour")):
                with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                    config(Path(directory), bad)

    def test_a_grade_must_be_defined_and_agree_with_its_confidence(self):
        grades = {"strongly_supported": {"label": "S", "meaning": "M", "confidence": "probable"},
                  "uncertain": {"label": "U", "meaning": "M", "confidence": "possible"}}
        self.assertEqual([], validate_case(case()) + grade_errors(case(), grades))
        self.assertEqual(["ada-parent.confidence must be probable for grade strongly_supported"],
                         grade_errors(case(confidence=C.DOCUMENTED), grades))
        self.assertIn("ada-parent.grade is not defined under [grades] in genealogy.toml: proved", grade_errors(case("proved"), grades))
        self.assertIn("ada-parent.grade must be a grade key", "\n".join(validate_case(case("Strongly supported"))))
        record = case().records("Relationship")[0]
        self.assertEqual(record, record_from_dict("Relationship", record.to_dict()))

    def test_the_site_prints_the_project_wording_and_explains_it(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "site"
            build_site(case(), config(Path(directory)), out)
            dossier = next(p for p in (out / "people").glob("*.html") if 'data-person-id="ada"' in p.read_text()).read_text()
            self.assertIn('href="../evidence.html#grade-strongly_supported" data-confidence="probable" data-grade="strongly_supported">Strongly supported (80%)</a>', dossier)
            self.assertIn('href="../evidence.html#grade-uncertain" data-status="supported" data-confidence="possible" data-grade="uncertain">Supported · Uncertain</a>', dossier)
            guide = (out / "evidence.html").read_text()
            self.assertIn("<h2>This project&#x27;s grades</h2>", guide)
            self.assertIn('<dt id="grade-strongly_supported">Strongly supported</dt><dd>Several independent records agree, short of proof. '
                          'Counted as probable wherever the site groups or colours by confidence.</dd>', guide)
            script = (out / "data/site-data.js").read_text()
            data = json.loads(script[script.index("{"):script.rindex("}") + 1])
            self.assertEqual({"strongly_supported": "Strongly supported", "uncertain": "Uncertain"}, data["site"]["grades"])
            self.assertEqual("strongly_supported", data["relationships"][0]["grade"])

    def test_a_site_without_grades_is_unchanged_and_an_undefined_grade_stops_the_build(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "site"
            build_site(case(grade=None), config(Path(directory), ""), out)
            self.assertNotIn("This project", (out / "evidence.html").read_text())
            self.assertNotIn('"grades"', (out / "data/site-data.js").read_text())
            with self.assertRaisesRegex(ValueError, "grade is not defined"):
                build_site(case(), config(Path(directory), ""), out)

    def test_validate_reports_an_undefined_grade(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "p"
            self.assertEqual(0, main(["init", str(root), "--name", "Fictional"]))
            store = next((root / "cases").glob("*.json"))
            stored = json.loads(store.read_text())
            stored["record_sets"] = case().to_dict()["record_sets"]
            store.write_text(json.dumps(stored))
            errors = io.StringIO()
            with redirect_stderr(errors):
                self.assertEqual(1, main(["--project", str(root), "validate"]))
            self.assertIn("ada-parent.grade is not defined under [grades]", errors.getvalue())
            (root / "genealogy.toml").write_text((root / "genealogy.toml").read_text() + GRADES_TOML)
            self.assertEqual(0, main(["--project", str(root), "validate"]))


if __name__ == "__main__":
    unittest.main()
