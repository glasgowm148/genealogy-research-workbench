"""Fictional fixtures for the project-database tests. No real people or records."""

from __future__ import annotations

from pathlib import Path
import tempfile

from genealogy.cli import initialize_project
from genealogy.store import NameInput, Research, open_project

GEDCOM_7 = """0 HEAD
1 GEDC
2 VERS 7.0
0 @I1@ INDI
1 NAME Wren /Harrow/
1 SEX M
1 BIRT
2 DATE 1801
2 PLAC Fennick, Marlshire
1 DEAT
2 DATE 1870
1 UID 0b1c2d3e-0000-4000-8000-000000000001
1 FAMS @F1@
0 @I2@ INDI
1 NAME Ione /Marsh/
1 SEX F
1 DEAT
2 DATE 1866
1 UID 0b1c2d3e-0000-4000-8000-000000000002
1 FAMS @F1@
0 @I3@ INDI
1 NAME Tamsin /Harrow/
1 SEX F
1 BIRT
2 DATE 1830
1 DEAT
2 DATE 1901
1 UID 0b1c2d3e-0000-4000-8000-000000000003
1 FAMC @F1@
1 _UNKNOWNTAG kept verbatim
0 @F1@ FAM
1 HUSB @I1@
1 WIFE @I2@
1 CHIL @I3@
0 TRLR
"""


class Fixture:
    """A temporary project with a few fictional people, sources and research items."""

    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="grwb-test-")
        self.root = Path(self.tmp.name)
        self.directory = self.root / "project"
        initialize_project(self.directory, "Harrow family study")
        self.project = open_project(self.directory)
        self.research = Research(self.project.store)

    def close(self) -> None:
        self.project.close()
        self.tmp.cleanup()

    def write(self, **kwargs):
        return self.project.store.write(actor=kwargs.pop("actor", "test"), **kwargs)

    def person(self, name: str, *, living: str = "deceased", access: str = "public", sex: str | None = None,
               birth: str | None = None, **kwargs) -> str:
        given, _, surname = name.partition(" ")
        with self.write() as tx:
            person_id = self.research.create_person(tx, names=[NameInput(name, given=given, surname=surname or None,
                                                                         preferred=True)],
                                                    living=living, access=access, sex=sex, **kwargs)
            if birth:
                self.research.add_event(tx, kind="birth", participants=[(person_id, "principal")], date_original=birth,
                                        date_start=birth, date_kind="exact", access=access)
        return person_id
