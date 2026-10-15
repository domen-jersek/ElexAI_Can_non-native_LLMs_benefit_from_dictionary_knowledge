# ELEXAI pilot: base LLM vs text RAG vs graph RAG over Slovene lexicographic data

Research pilot for [ELEXAI](https://elex.is/) (Horizon Europe, 2026-2029; FRI project 2813):
does lexicographic knowledge (a dictionary, a knowledge graph) improve LLM answers?

**Task.** One dictionary (the Digital Dictionary Database of Slovene, DDDS) and one
question type (sense disambiguation of polysemous words). Three variants share the
same LLM, the same question set and the same prompts; only the supplied context differs:

| Variant | Context |
|---|---|
| A | none - base LLM |
| B | text RAG over per-sense dictionary chunks (exact vector search) |
| C | graph RAG: senses + dictionary/WordNet structure from Neo4j |
| oracle | gold sense always supplied - isolates answer-composition errors |

**Metrics.** Answer correctness, source-citation correctness (does the cited sense id
match the gold id), latency (p50/p95), retrieval recall@k, and a separate
retrieval-error vs answer-composition-error analysis. Paired comparisons use
McNemar's test plus bootstrap confidence intervals (small N is expected).

## Status

- [x] **Phase 0** - scaffold, source registration (`data/MANIFEST.json`), data inspection,
      DDDS snapshot restored into Postgres (see `docs/DATA.md`)
- [ ] Phase 1 - graph build (Neo4j: DDDS senses/relations + Open Slovene WordNet)
- [ ] Phase 2 - variants A + B (runner, retrieval, response cache, run manifests)
- [ ] Phase 3 - variant C (graph retrieval)
- [ ] Phase 4 - evaluation, error decomposition, statistics, report + plots

## Quickstart

Prerequisites: [uv](https://docs.astral.sh/uv/), Docker Desktop, GNU make
(on Windows: `winget install GnuWin32.Make`).

```bash
cp .env.example .env          # fill in credentials / API key (see docs/REPRODUCE.md)
make setup                    # uv sync: pinned Python 3.12.8 + uv.lock
make data                     # fetch missing CLARIN.SI sources; verify MANIFEST.json
# DDDS snapshot: obtained manually - see docs/DATA.md (then it is verified too)
make db                       # start Postgres + restore the DDDS snapshot subset
make test                     # unit tests
make lint                     # ruff + mypy

uv run python scripts/inspect_data.py   # Phase-0 source inspection report
```

`make help` is not implemented; the targets are `setup data db graph index run eval test lint clean`.

## Layout

```
configs/            one YAML per experiment (validated with pydantic, no hardcoded models)
data/
  MANIFEST.json     committed sha256 manifest of everything under data/raw/
  raw/              raw sources (gitignored; DDDS dump + CLARIN.SI data)
  processed/        derived exports (gitignored; regenerable)
  questions/        the question set with gold answers + review status (committed)
docs/               DATA.md, DECISIONS.md, REPRODUCE.md
runs/               per-run artifacts (gitignored; regenerable from cache)
scripts/            thin CLIs (download, register, db_restore, inspect, ...)
src/elexai/         sources/ graph/ retrieval/ llm/ eval/ runner/
tests/              unit tests
```

## Documentation map

| File | Contents |
|---|---|
| `docs/DATA.md` | what each source contains (verified numbers), quality caveats, licensing |
| `docs/DECISIONS.md` | decision log with rationale - read this first |
| `docs/REPRODUCE.md` | exact steps from a clean clone to reproduced results |
| `AGENTS.md` | working rules for contributors (human or AI) |

## Attribution and licensing

CLARIN.SI sources are CC BY-SA 4.0 (sloWNet 3.1, OSWN 1.0, Sloleks 3.1) or CC BY 4.0
(OSWN <-> DDDS linked senses). The DDDS snapshot comes from the CJVT wiki distribution
page; **no license is stated - treat it as internal research data and do not
redistribute**. See `docs/DATA.md` for details.
