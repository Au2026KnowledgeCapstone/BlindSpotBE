PYTHON ?= python3
VENV ?= .venv

.PHONY: initialize run
initialize:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/python -m pip install -r requirements.txt

run:
	$(VENV)/bin/python -m uvicorn backend.main:app --host localhost --port 8000 --reload
