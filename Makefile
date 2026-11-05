PYTHON ?= python3
VENV ?= .venv

.PHONY: initialize run
initialize:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/python -m pip install -e '.[test]'

run:
	$(VENV)/bin/uvicorn main:app --reload --host 0.0.0.0 --port 8000
