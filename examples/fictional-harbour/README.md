# Fictional Harbour

Entirely invented names, places, relationships, sources and events used to
demonstrate configured cases and views plus `genealogy validate`, `ingest`,
`search`, `report`, `build`, and `export`.

From the toolkit checkout, run the example without modifying it:

```sh
PYTHONPATH=src python -m genealogy --project examples/fictional-harbour validate
PYTHONPATH=src python -m genealogy --project examples/fictional-harbour search Harbour
PYTHONPATH=src python -m genealogy --project examples/fictional-harbour report --format markdown
PYTHONPATH=src python -m genealogy --project examples/fictional-harbour build --output /tmp/fictional-harbour-views
```

Copy the project to a temporary directory before trying the supplied GEDCOM,
archive JSON, or tabular inputs, because `ingest` durably updates its selected case.
