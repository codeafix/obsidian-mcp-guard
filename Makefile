# Use the project venv if present (local dev); otherwise fall back to python3 (CI).
ifneq ($(wildcard .venv/bin/python),)
    PYTHON ?= .venv/bin/python
else
    PYTHON ?= python3
endif

.PHONY: install test build clean help

help:
	@echo "Targets:"
	@echo "  install  Install the package and test dependencies"
	@echo "  test     Run the test suite with coverage"
	@echo "  build    Build source and wheel distributions"
	@echo "  clean    Remove build artefacts and cache files"

install:
	$(PYTHON) -m pip install -e .
	$(PYTHON) -m pip install pytest pytest-cov

test:
	$(PYTHON) -m pytest tests/ --cov=obsidian_mcp_guard --cov-report=term-missing --cov-fail-under=90

build:
	$(PYTHON) -m pip install build
	$(PYTHON) -m build

clean:
	rm -rf dist/ build/ .coverage htmlcov/
	find . -path ./.venv -prune -o -type d -name __pycache__ -print -exec rm -rf {} +
	find . -path ./.venv -prune -o -type f -name "*.pyc" -print -delete
