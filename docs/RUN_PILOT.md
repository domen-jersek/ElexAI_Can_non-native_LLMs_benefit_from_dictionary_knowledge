# RUN_PILOT.md - how to run the pilot tests yourself

This is the guide for running the actual experiments (variants A/B/C/D/oracle over the
DDDS dictionary). The platform is already built, the database is restored and the
question set (36 drafts) is validated; you only need an OpenRouter API key and two
commands. Models that are reachable only through a chat UI are covered in section 6.

## 0. One-time: add your API key

Edit `.env` in the repository root and set:

```
OPENROUTER_API_KEY=sk-or-...your key...
```

(The code reads whichever environment variable the config names - see
`llm.api_key_env` in `configs/skeleton.yaml`; the key is never logged or written to
the repo. `.env` is gitignored.)

## 1. Build the search index for variant B (one-time, no API key needed)

Variant B needs the embedded index of all sense chunks (131,056 senses):

```
make index CONFIG=configs/skeleton.yaml
```

- Uses **BGE-M3** (pinned revision) on CPU: expect **~1-2 hours** the first time
  (model download ~2.3 GB + encoding). The result is cached under
  `data/processed/index/bge-m3@5617a9f61b02/` - never rebuilt unless you delete it.
- A faster smoke alternative (small model, only the first 20k chunks, ~10 min):
  `make index CONFIG=configs/smoke.yaml`.

## 2. Run the experiment (needs the API key)

```
uv run python -m elexai.runner configs/skeleton.yaml
```

- 22 questions x 5 variants = **110 LLM calls**; with the default model
  (`openai/gpt-6-luna`, OpenRouter) this costs roughly **a few cents** and takes
  a few minutes. Variant D needs the graph loaded first (section 2b); the
  A/B/C/oracle answers are served from the response cache if you ran them before
  (free and identical).
- Every request/response pair is cached in `.cache/llm/` (keyed by model + params +
  full prompt). Re-running is free and offline; delete the folder only if you change
  the prompt template on purpose.
- Output: `runs/<timestamp>_skeleton/` with:
  - `answers.jsonl` - one line per call: full prompt, retrieved candidates and
    scores, raw model output, parsed answer, latency, cache flag;
  - `manifest.json` - git commit, data-manifest hash, model/embedder pins, template
    version, seeds;
  - `config.resolved.yaml` - the exact configuration used.

Quick taste before spending anything: `uv run python -m elexai.runner configs/skeleton.yaml --limit 3`
(3 questions per variant) or `--dry-run` (stub model, no API key, plumbing check).

## 2b. Variant D (graph RAG): one-time load

```
uv run python scripts/load_graph.py      # reads NEO4J_* from .env; ~5-10 minutes
```

- Start your Neo4j Desktop database first. Recommended for this first v2 load:
  wipe the graph in Neo4j Browser first (`MATCH (n) DETACH DELETE n`), then run
  the loader; it is idempotent (MERGE everywhere), so future re-runs are safe.
- The loader now also loads: OSWN Synset nodes (glosses, literals), the WordNet
  hierarchy (from the OEWN 2023 release - OSWN ids are OEWN ids, verified 99.98%),
  sense->synset links (exact-lemma by default; `--include-approx` for the fuzzy
  ones) and phrase->component-word edges.
- Counts to expect in its final report: senses 131056, synsets 95262,
  IN_SYNSET ~83179 (exact default), COLLOCATES_WITH ~986k, HAS_PART in the
  millions, and synset relation edges in the tens of thousands (per-type
  counts are printed; HYPERNYM should clearly dominate).
- `--quick` loads only the first 2000 senses (no synsets/parts) for a smoke test.

## 3. Score and read the report

```
make eval            # evaluates the most recent run
# or: make eval RUN=<run_id>
```

Writes `metrics.json` + `report.md` next to the answers and prints a summary table.

### How to read the results

| Column | Meaning |
|---|---|
| citation acc. | share of answers whose cited DDDS sense ID matches the gold ID (variants B/C/oracle) |
| cite `none` | times the model refused to cite an ID |
| answer F1 / acc. | token-F1 of the free-text answer vs the draft gold answer; accuracy uses the threshold from the config (`eval.answer_f1_threshold`) |
| latency p50/p95 | milliseconds per call, cache hits excluded |
| retrieval/coverage errors | variant B: gold sense was not retrieved at all; variant C/oracle: gold sense was not among the shown candidates |
| composition errors | the gold sense WAS available but the model still answered wrong |
| recall@k | variant B only: is the gold sense in the top-k retrieved senses |

The key comparison for the research question: **does C (structured) beat B (text
search), and does either beat A?** The error split tells you *why* something failed
(finding the right entry vs. using it correctly). The oracle row is the upper bound:
if oracle makes the same mistakes as B/C, the problem is answer composition, not
retrieval.

## 4. Honest caveats (also printed in the report)

- The 22 questions are **drafts** written by the assistant; a lexicographer must
  verify answers and context sentences before the numbers are citable. Until then,
  treat results as a pilot signal, not final measurements.
- Small N (~22 questions): differences of one or two questions move percentages a
  lot. Statistical analysis (McNemar, bootstrap CIs) and plots come in the next
  phase; if you want more signal first, expand the question file and re-run - the
  pipeline needs no changes.
- Latency includes network/provider variance.

## 5. Common tweaks (all via config files, no code changes)

- **Different model**: `llm.model` in the config (same config = same model for all
  variants, as the experiment requires).
- **Different embedder / more or fewer retrieved senses**: `embedder.*` and
  `retrieval.k` (rebuild the index when the embedder changes; k needs no rebuild).
- **Questions**: edit `data/questions/questions.jsonl` (schema + validator:
  `uv run python scripts/validate_questions.py --senses data/processed/ddds/senses.jsonl`).

## 6. Chat-only models (GaMS on povejmo.si)

The GaMS models (CJVT/FRI) have no API - the only public access is the chat at
<https://povejmo.si> (`robots.txt` disallows `/api`, so only the UI is used). The
same run format is produced in two ways; both are documented in
`src/elexai/manual.py` and `src/elexai/scrape_povejmo.py`.

**a) Manual kit** - export the exact prompts of an existing run, fill them by hand,
import them back:

```
uv run python scripts/export_manual_prompts.py --run 20261022-091557_skeleton
uv run python scripts/import_manual_answers.py --source-run 20261022-091557_skeleton \
    --csv manual_kit/answers_gams3-12b.csv --name gams3-12b \
    --model-label "GaMS3-12B-Instruct (povejmo.si, 2026-10-27)"
make eval RUN=<printed run id>
```

The import copies the model-independent contexts (candidates, retrieval, graph
evidence) from the source run and replaces only the model outputs; the run
manifest is marked `manual: true`.

**b) UI scraper** - drives a visible browser like a human (selects the model,
opens a fresh chat per prompt, waits for the reply to stop changing, saves it into
the answers CSV):

```
uv run python scripts/scrape_povejmo.py --inspect                      # dump UI structure, sends nothing
uv run python scripts/scrape_povejmo.py --csv manual_kit/answers_gams3-12b.csv \
    --model "GaMS3-12B-Instruct" --limit 3                             # pilot
uv run python scripts/scrape_povejmo.py --csv manual_kit/answers_gams3-12b.csv \
    --model "GaMS3-12B-Instruct"                                       # the batch (resumable)
```

Safety: the only file written is the answers CSV (atomic replace, one-time `.bak`
copy); prompts are only read; failures are screenshotted into
`manual_kit/scrape_debug/` and the batch stops after three consecutive failures.
Already-answered rows are skipped, so any run can be resumed; pacing is human-like
(10 s between prompts) - do not run two scrapers at once. A reply is accepted only
when it carries the required `SENSE_ID`/`ODGOVOR` format (the "Razmišljam..."
thinking bubble is ignored); a send that does not register is retried and then
fails fast, leaving the row empty for a later retry.

Caveats: these are observations of a hosted product - the served model version is
not pinned and latency is not logged, so record the exact UI label and date in
`--model-label`. Variant A is scored on the answer text (token-F1), B/C/D/oracle
on the cited sense ID, exactly as in the API runs.

## Troubleshooting

- `environment variable 'OPENROUTER_API_KEY' is not set` -> add it to `.env`.
- `variant B needs a vector index at ...` -> run the `make index` step (config must
  match the one you run).
- `question validation failed` -> fix the listed lines in `questions.jsonl`.
- Docker/Postgres are only needed to *regenerate exports* (`make db`, `make core`);
  running and evaluating experiments does not need the database.
