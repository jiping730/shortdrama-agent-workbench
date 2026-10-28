.PHONY: install test lint run demo export

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest -q --basetemp=.pytest-tmp

lint:
	python -m compileall agent_platform tests

run:
	python -m uvicorn agent_platform.api:app --reload

demo:
	python -m agent_platform.cli workflow list
	python -m agent_platform.cli run create --project-id demo --script-file examples/sample_script.txt

export:
	python -m agent_platform.cli export html --run-id $(RUN_ID) --output exports/run.html
