PYTHON ?= python3
VENV ?= .venv

.PHONY: initialize run test openapi

initialize:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/python -m pip install -e '.[test]'

run:
	$(VENV)/bin/uvicorn main:app --reload --host 0.0.0.0 --port 8000

test:
	$(VENV)/bin/python -m pip install -q -e '.[test]'
	$(VENV)/bin/python -m pytest -q

# Regenerate the committed API contract. The frontend generates its client
# from this, so it is checked in rather than built on demand.
openapi:
	$(VENV)/bin/python -c "import json, main, pathlib; pathlib.Path('docs/openapi.json').write_text(json.dumps(main.app.openapi(), indent=2) + '\n')"
	@echo "wrote docs/openapi.json"
