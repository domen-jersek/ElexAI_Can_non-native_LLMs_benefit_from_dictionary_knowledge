# ELEXAI pilot - common tasks (see README.md and docs/RUN_PILOT.md).
# NOTE: on Windows, GNU make is required (installed via `winget install GnuWin32.Make`).

PY ?= uv run python
CONFIG ?= configs/skeleton.yaml
ARGS ?=

.PHONY: setup data db core graph index run eval test lint clean

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

## Export the lexical core (senses + definitions + relations) from the database.
core:
	uv run python scripts/export_lexical_core.py

## Build the Neo4j knowledge graph (Phase 1; not implemented yet).
graph:
	uv run python scripts/build_graph.py

## Build the exact vector index for variant B (make index CONFIG=configs/skeleton.yaml).
index:
	uv run python scripts/build_index.py --config $(CONFIG)

## Run an experiment: make run CONFIG=configs/skeleton.yaml ARGS="--limit 5 --dry-run"
run:
	$(PY) -m elexai.runner $(CONFIG) $(ARGS)

## Evaluate the most recent run (or: make eval RUN=<run_id>).
eval:
	uv run python scripts/evaluate.py $(if $(RUN),--run $(RUN),--last)

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
