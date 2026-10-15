# ELEXAI pilot - common tasks (see README.md for the full quickstart).
# NOTE: on Windows, GNU make is required (installed via `winget install GnuWin32.Make`).

PY ?= uv run python

.PHONY: setup data db graph index run eval test lint clean

## Create/refresh the uv environment (installs the pinned Python + dependencies).
setup:
	uv sync

## Download and/or verify the source data and refresh data/MANIFEST.json.
data:
	uv run python scripts/download_data.py
	uv run python scripts/register_data.py --verify

## Start Postgres and restore the DDDS snapshot subset into it (see scripts/db_restore.py).
db:
	uv run python scripts/db_restore.py

## Build the Neo4j knowledge graph (Phase 1; not implemented yet).
graph:
	uv run python scripts/build_graph.py

## Build the text-RAG index (Phase 2; not implemented yet).
index:
	uv run python scripts/build_index.py

## Run an experiment: make run CONFIG=configs/example.yaml
run:
	$(PY) -m elexai.runner $(CONFIG)

## Evaluate one or more runs (Phase 4; not implemented yet).
eval:
	uv run python scripts/evaluate.py

## Run the test suite.
test:
	uv run pytest

## Lint and type-check.
lint:
	uv run ruff check .
	uv run mypy

## Remove caches and local artifacts (keeps data/raw and docs/).
clean:
	uv run python scripts/clean.py
