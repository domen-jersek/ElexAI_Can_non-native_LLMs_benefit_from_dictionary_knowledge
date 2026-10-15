# AGENTS.md - working rules in this repository

For any contributor (human or AI agent) touching this codebase.

## Context in one paragraph

ELEXAI pilot: we test whether lexicographic knowledge improves LLM answers on Slovene
sense disambiguation. Scope: ONE dictionary (DDDS snapshot, restored into Postgres) and
ONE question type. Variants: A = base LLM; B = same LLM + text RAG over per-sense
dictionary chunks; C = same LLM + graph RAG (DDDS + Open Slovene WordNet in Neo4j);
oracle = gold sense supplied, to isolate composition errors. The LLM, the questions and
the prompt templates are identical across variants - only the context differs. Metrics:
answer correctness, source-citation correctness, latency; retrieval errors vs
composition errors analysed separately. Klemen owns the research question, data model
and methodology; the engineering lives here. See docs/DECISIONS.md for the decision log.

## Hard rules

1. **Environment**: Python 3.12.8 via uv only. Use `uv run ...` / `uv add ...`;
   never `pip install`. `uv.lock` is committed; keep it in sync.
2. **No hardcoding** of LLM model ids, embedders or retrieval depth anywhere in code.
   Every experiment is one YAML in `configs/`, validated by `src/elexai/config.py`
   (pydantic). Changing the embedder or `k` must require zero code changes.
3. **Determinism**: temperature 0, fixed seeds, exact (non-ANN) vector search
   (FAISS flat). The on-disk LLM response cache (keyed by hash of model + params +
   full prompt) is the source of truth for published numbers; document honestly that
   raw API outputs are not bit-identical across hardware/providers.
4. **Run manifests**: every run writes `runs/<run_id>/` with the resolved config,
   git commit + dirty flag, uv.lock hash, data manifest hash, model ids/revisions,
   seeds, timestamps, raw LLM inputs/outputs (JSONL), retrieved contexts, metrics, logs.
5. **Raw data is immutable.** `data/raw/**` is read-only and gitignored. Integrity is
   checked via `make data` against committed `data/MANIFEST.json`.
6. **DDDS snapshot privacy**: the dump is a production-like dictionary database.
   Never restore, export or publish `auth_*`, `django_*` (except `django_content_type`),
   `jet_*`, session data or editor working logs. The exclusion list lives in
   `scripts/db_restore.py` (`EXCLUDED_TABLES`); keep it in sync with docs/DECISIONS.md.
7. **Source adapters**: all access to source data goes through
   `src/elexai/sources/*` (see `base.py`). Retrieval, graph-loading and evaluation code
   must not import psycopg or know about DDDS tables directly.
8. **Docs are part of the deliverable.** If you learn a new fact about the data,
   update `docs/DATA.md`; if you make a non-obvious decision, add an entry to
   `docs/DECISIONS.md` (numbered, dated, with rationale).
9. **Phases**: work in phases; at the end of each phase STOP, summarize what was done
   and what was learned, and wait for confirmation before starting the next one.
10. **Questions and gold answers**: the schema is in `src/elexai/questions.py`
    (`review_status` draft|verified, reviewer, notes). Gold answers must ultimately be
    verified by a lexicographer - never silently upgrade a draft to verified.

## Commands cheat sheet

| Command | What it does |
|---|---|
| `make setup` | create/refresh the uv environment |
| `make data` | download missing sources + verify MANIFEST hashes |
| `make db` | start Postgres (docker compose) + restore DDDS snapshot subset |
| `make graph` | build the Neo4j graph (Phase 1, not implemented yet) |
| `make index` | build the text-RAG index (Phase 2, not implemented yet) |
| `make run CONFIG=configs/x.yaml` | run one experiment |
| `uv run python scripts/inspect_data.py` | source inspection report |
| `make test` / `make lint` | pytest / ruff + mypy |

## Where things live

- `src/elexai/sources/` - catalog + adapters (DDDS helper now, full adapter Phase 1)
- `src/elexai/{graph,retrieval,llm,eval,runner}/` - later phases, one package each
- `scripts/` - thin CLIs; logic belongs in `src/elexai`
- `data/raw/<subdir>/` - one folder per source (see `src/elexai/sources/catalog.py`)
