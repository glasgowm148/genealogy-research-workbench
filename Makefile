PYTHON ?= python3

.PHONY: test check example package browser-check

test:
	$(PYTHON) -m unittest discover -s tests -v

check:
	$(PYTHON) -m ruff check src tests tools
	$(MAKE) test

example:
	$(PYTHON) -m genealogy --project examples/fictional-harbour build --output dist

package:
	$(PYTHON) -m build

browser-check:
	$(PYTHON) tools/browser_check.py
