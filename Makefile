PYTHON ?= python3
VENV ?= .venv

.PHONY: initialize run
initialize:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/python -m pip install -r requirements.txt

run: $(VENV)/bin/python
	$(VENV)/bin/python backend/main.py

$(VENV)/bin/python:
	$(MAKE) initialize
