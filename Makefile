PYTHON ?= python3

.PHONY: test check example package browser-check

test:
	$(PYTHON) -m unittest discover -s tests -v

check:
	$(PYTHON) -m ruff check src tests
	$(MAKE) test

example:
	$(PYTHON) -m genealogy --project examples/fictional-harbour build --output dist

package:
	$(PYTHON) -m build

browser-check:
	GENEALOGY_BROWSER_TESTS=1 $(PYTHON) -m unittest discover -s tests -p 'test_browser*.py' -v
