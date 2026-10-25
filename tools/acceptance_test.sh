#!/bin/sh
# Independent-installation acceptance test for genealogy-research-workbench.
#
# Installs a built wheel into a brand-new virtual environment and runs the
# whole user workflow on an invented family in a directory outside every
# source checkout, with PYTHONPATH unset and the working directory elsewhere,
# so nothing can be imported from a checkout by accident.
#
#   tools/acceptance_test.sh dist/genealogy_research_workbench-X.Y.Z-py3-none-any.whl [WORKDIR]
set -eu

WHEEL=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
WORK=${2:-$(mktemp -d "${TMPDIR:-/tmp}/grwb-acceptance.XXXXXX")}
unset PYTHONPATH PYTHONHOME
mkdir -p "$WORK"
WORK=$(cd "$WORK" && pwd -P)
cd "$WORK"
python3 -m venv venv
venv/bin/python -m pip install --quiet --no-index --no-deps "$WHEEL"
G="$WORK/venv/bin/genealogy"
absent() { if grep -rq "$1" "$2"; then echo "LEAK: $1 found in $2"; exit 1; fi; }
step() { printf '\n== %s\n' "$*"; }

step "the installed package is the wheel, not a checkout"
venv/bin/python -I -c "import genealogy, os, sys; p = os.path.realpath(genealogy.__file__); print(p); sys.exit(0 if p.startswith('$WORK/venv/') else 1)"
"$G" --version

step "initialise an independent project"
"$G" init fenwick --name "The Fenwick family (fictional)"
P="--project $WORK/fenwick"

cat > family.ged <<'GED'
0 HEAD
1 GEDC
2 VERS 7.0
0 @I1@ INDI
1 NAME Hollis /Fenwick/
1 SEX M
1 BIRT
2 DATE 1790
2 PLAC Marrow End, Invented Shire
1 DEAT
2 DATE 1861
1 UID 3f7e0000-0000-4000-8000-000000000001
0 @I2@ INDI
1 NAME Mara /Quill/
1 SEX F
1 DEAT
2 DATE 1858
1 UID 3f7e0000-0000-4000-8000-000000000002
0 @I3@ INDI
1 NAME Isaac /Fenwick/
1 SEX M
1 BIRT
2 DATE 1821
1 DEAT
2 DATE 1890
1 UID 3f7e0000-0000-4000-8000-000000000003
1 FAMC @F1@
0 @I4@ INDI
1 NAME Nova /Fenwick/
1 BIRT
2 DATE 1995
1 UID 3f7e0000-0000-4000-8000-000000000004
0 @F1@ FAM
1 HUSB @I1@
1 WIFE @I2@
1 CHIL @I3@
0 TRLR
GED

step "import a GEDCOM file (and prove a repeat import is a no-op)"
"$G" $P import family.ged --publish-deceased > import.json
"$G" $P import family.ged --publish-deceased --update | grep -q '"unchanged"'

step "sources, a record, a citation, mentions and an unresolved identity"
"$G" $P source add "Invented parish register" --repository "Invented Record Office" --access public > source.id
"$G" $P record add baptism --title "Baptism of Isaac, 1821" --source "$(cat source.id)" --date "3 June 1821" \
  --summary "Names Isaac son of Hollis." --access public > record.id
"$G" $P citation add --source "$(cat source.id)" --record "$(cat record.id)" --locator "folio 12" --access public > citation.id
"$G" $P mention add "$(cat record.id)" "Isaac" --role child > child.mention
"$G" $P mention add "$(cat record.id)" "Hollis Fenwick" --role father > father.mention
"$G" $P person add "Isaac Fenwick" --record-defined --label "Marrow End Isaac" --living deceased > other-isaac.id
ISAAC=$("$G" $P person list | venv/bin/python -c "import json,sys; print(next(p['id'] for p in json.load(sys.stdin) if (p['names'] or '').startswith('Isaac') and p['label'] != 'Marrow End Isaac'))")
HOLLIS=$("$G" $P person list | venv/bin/python -c "import json,sys; print(next(p['id'] for p in json.load(sys.stdin) if (p['names'] or '').startswith('Hollis')))")
"$G" $P identify "$(cat child.mention)" "$ISAAC" --status "preferred" > identity-1.id
"$G" $P identify "$(cat child.mention)" "$(cat other-isaac.id)" --status "compatible alternative" > identity-2.id
"$G" $P question add "Is the baptised Isaac the Isaac who died in 1890?" --about "$ISAAC" \
  --resume-when "the 1841 returns are indexed" --access public > question.id
"$G" $P hypothesis add "Marrow End Isaac and Isaac Fenwick are one man" --kind identity --about "$ISAAC" \
  --about "$(cat other-isaac.id)" > hypothesis.id

step "an assessment and a later revision, with the stale-update guard"
"$G" $P relationship add "$ISAAC" father "$HOLLIS" --access public > claim.id
"$G" $P evidence add "$(cat claim.id)" --citation "$(cat citation.id)" --interpretation "The baptism names Hollis."
"$G" $P assess "$(cat claim.id)" --status possible --estimate 44 --reasoning "Same parish, compatible age."
if "$G" $P assess "$(cat claim.id)" --status proved --estimate 95 2> stale.txt; then exit 1; fi
grep -q "expected-revision" stale.txt
"$G" $P assess "$(cat claim.id)" --expected-revision 1 --status proved --estimate 95 --reasoning "The baptism names him."
"$G" $P history "$(cat claim.id)" | venv/bin/python -c "import json,sys; h=json.load(sys.stdin)['history']; assert [r['estimate_percent'] for r in h] == [44, 95], h"
"$G" $P search add s-burials "Invented burials 1880-1895" --result "nothing found" --for "$ISAAC" --sensitivity public

step "validate, then build a privacy-filtered site"
"$G" $P validate
"$G" $P build
test -f fenwick/dist/index.html
absent "Nova" fenwick/dist
absent "Marrow End Isaac" fenwick/dist
grep -rq "Isaac Fenwick" fenwick/dist

step "native and GEDCOM exports"
"$G" $P native export fenwick/private/exports/full.json
"$G" $P gedcom export fenwick/private/exports/family-7.ged --version 7.0 --private
"$G" $P gedcom export public-551.ged --version 5.5.1
grep -q "2 VERS 5.5.1" public-551.ged
absent "Nova" public-551.ged
test -f public-551.ged.report.json

step "backup and restore into a fresh location"
"$G" $P backup create "$WORK/backup"
"$G" backup verify "$WORK/backup"
"$G" backup restore "$WORK/backup" "$WORK/restored"
"$G" --project "$WORK/restored" validate
"$G" --project "$WORK/restored" native export "$WORK/restored-full.json"
venv/bin/python -c "import json; a=json.load(open('$WORK/fenwick/private/exports/full.json')); b=json.load(open('$WORK/restored-full.json')); assert a == b"

step "upgrade an earlier JSON-case project; its customisation survives"
mkdir -p old/cases
cat > old/genealogy.toml <<'TOML'
[project]
name = "The Quill papers (fictional)"
case_directory = "cases"
default_case = "quill"

[[catalogue.views]]
label = "Quill family"
query = "q=Quill"

[exports]
directory = "dist"
TOML
cat > old/cases/quill.json <<'JSON'
{"schema_version": 1, "id": "quill", "title": "Quill papers", "question_ids": ["q-1"], "finding_ids": ["f-1"],
 "record_sets": {
  "Person": [{"id": "person:ada", "names": [{"value": "Ada Quill"}], "living": "deceased", "sensitivity": "public"}],
  "ResearchQuestion": [{"id": "q-1", "question": "Where was Ada born?", "related_ids": ["person:ada"], "sensitivity": "public"}],
  "Finding": [{"id": "f-1", "conclusion": "Ada signed the 1840 lease.", "related_ids": ["person:ada"], "status": "draft", "sensitivity": "public"}]}}
JSON
cp old/genealogy.toml old-config-before.toml
if "$G" --project old build 2> legacy.txt; then exit 1; fi
grep -q "upgrade" legacy.txt
"$G" --project old upgrade
"$G" --project old upgrade | grep -q '"cases/quill.json"'
cmp old/genealogy.toml old-config-before.toml
"$G" --project old build
grep -rq "Quill family" old/dist
grep -rq "Ada Quill" old/dist
"$G" --project old db status

printf '\nAcceptance workflow passed in %s\n' "$WORK"
