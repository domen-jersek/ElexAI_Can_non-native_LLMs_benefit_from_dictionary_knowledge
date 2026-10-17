# ELEXAI pilot: base LLM vs text RAG vs structured knowledge over Slovene dictionary data

Research pilot for [ELEXAI](https://elex.is/) (Horizon Europe, 2026-2029; FRI project 2813):
does lexicographic knowledge (a dictionary, structured senses) improve LLM answers?

**Task.** One dictionary (the Digital Dictionary Database of Slovene, DDDS) and one
question type (sense disambiguation of polysemous words). All variants share the same
LLM, the same question set and the same prompt template; only the supplied context
differs:

| Variant | Context |
|---|---|
| A | none - base LLM |
| B | text RAG: exact vector search (FAISS) over one chunk per dictionary sense |
| C | structured data: exact lemma lookup - all senses with definitions, synonyms and typical collocations ("Zveze") |
| D | graph RAG: the same candidates, ranked by how well the sentence matches each sense's neighborhood in Neo4j |
| oracle | gold sense + neighbouring senses of the same lemma - isolates answer-composition errors |

**Metrics.** Answer correctness, source-citation correctness (does the cited sense id
match the gold id), latency (p50/p95), retrieval recall@k, and a separate
retrieval/coverage-error vs answer-composition-error analysis. Scoring is LLM-free
and separate from generation.

## Status

- [x] **Phase 0** - scaffold, source registration (`data/MANIFEST.json`), DDDS snapshot
      restored + inspected (`docs/DATA.md`)
- [x] **Phase 0.5** - walking skeleton: variants A/B/C/oracle runnable end-to-end,
      response cache, run manifests, LLM-free scoring + reports; 22 DRAFT questions.
      How to run it yourself: **`docs/RUN_PILOT.md`**
- [ ] Phase 1 - lexicographer verifies/replaces the draft questions; expand the set
- [ ] Phase 2 - full evaluation round: statistics (McNemar + bootstrap CIs), plots,
      error-analysis report
- [ ] Phase 3 - optional: Neo4j graph backend for variant C; LinkingTK-based
      OSWN <-> DDDS re-link (spike validated, positive: see `docs/LINKINGTK_SPIKE.md`)

## Quickstart

Prerequisites: [uv](https://docs.astral.sh/uv/), Docker Desktop, GNU make
(on Windows: `winget install GnuWin32.Make`).

```bash
cp .env.example .env          # fill in credentials / API key
make setup                    # uv sync: pinned Python 3.12.8 + uv.lock
make data                     # fetch missing CLARIN.SI sources; verify MANIFEST.json
# DDDS snapshot: obtained manually - see docs/DATA.md (then it is verified too)
make db                       # start Postgres + restore the DDDS snapshot subset
make core                     # export the lexical core (senses + definitions + relations)
make test                     # unit tests
make lint                     # ruff + mypy
```

### Run the pilot experiments

```bash
# in .env: OPENROUTER_API_KEY=...
make index CONFIG=configs/skeleton.yaml            # one-time; BGE-M3, ~1-2 h on CPU
uv run python -m elexai.runner configs/skeleton.yaml   # 22 questions x 4 variants
make eval                                          # metrics + runs/<id>/report.md
```

Full walkthrough, costs, and how to read the results: **`docs/RUN_PILOT.md`**.

## Layout

```
configs/            one YAML per experiment (validated with pydantic, no hardcoded models)
data/
  MANIFEST.json     committed sha256 manifest of everything under data/raw/
  raw/              raw sources (gitignored; DDDS dump + CLARIN.SI data)
  processed/        derived exports: ddds/lexical_core.jsonl, index/ (gitignored)
  questions/        the question set with gold answers + review status (committed)
docs/               DATA.md, DECISIONS.md, REPRODUCE.md, RUN_PILOT.md
runs/               per-run artifacts: answers.jsonl, manifest.json, metrics, report
scripts/            thin CLIs (download, register, db_restore, export, index, evaluate)
src/elexai/         sources/ graph/ retrieval/ llm/ eval/ runner/
tests/              unit tests
```

## Documentation map

| File | Contents |
|---|---|
| `docs/RUN_PILOT.md` | how to run the experiments yourself (API key, index, runs, how to read results) |
| `docs/DATA.md` | what each source contains (verified numbers), quality caveats, licensing |
| `docs/DECISIONS.md` | decision log with rationale - read this first |
| `docs/REPRODUCE.md` | exact steps from a clean clone to reproduced results |
| `AGENTS.md` | working rules for contributors (human or AI) |

## Attribution and licensing

CLARIN.SI sources are CC BY-SA 4.0 (sloWNet 3.1, OSWN 1.0, Sloleks 3.1) or CC BY 4.0
(OSWN <-> DDDS linked senses). The DDDS snapshot comes from the CJVT wiki distribution
page; **no license is stated - treat it as internal research data and do not
redistribute**. See `docs/DATA.md` for details.
