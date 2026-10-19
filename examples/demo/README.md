# The Alderwick Family: fictional demo

This is a wholly synthetic showcase with 42 invented, deceased people across four generations, three invented place labels, supplied illustrative coordinates, invented citations, research findings, questions and uncertain hypotheses. It contains no real family data, real records, provider identifiers, DNA, or network-dependent steps. Every case record is explicitly marked public so the people, tree, map, timeline, source and research views can be demonstrated safely.

The source titles and locators are fabricated teaching examples, not citations to actual archives. Coordinates are illustrative and do not identify the fictional places.

Regenerate the durable case and equivalent GEDCOM and OneTree-import inputs deterministically:

```sh
python examples/demo/create_demo.py
```

Validate and render the showcase from the toolkit checkout:

```sh
PYTHONPATH=src python -m genealogy --project examples/demo validate
PYTHONPATH=src python -m genealogy --project examples/demo report --format markdown
PYTHONPATH=src python -m genealogy --project examples/demo build --output /tmp/alderwick-demo-views
```

The import fixtures in `input/` use the same fictional people and parent outline. Their imported relationship confidence is intentionally unknown; the curated demo case carries its separately assessed confidence and evidence.
