# RUN_PILOT.md - how to run the pilot tests yourself

This is the guide for running the actual experiments (variants A/B/C/oracle over the
DDDS dictionary). The platform is already built, the database is restored and the
question set (22 drafts) is validated; you only need an OpenRouter API key and two
commands.

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
  hierarchy (from sloWNet, mapped by PWN offset), sense->synset links
  (exact-lemma by default; `--include-approx` for the fuzzy ones) and
  phrase->component-word edges.
- Counts to expect in its final report: senses 131056, synsets 95262,
  IN_SYNSET ~83179 (exact default), COLLOCATES_WITH ~986k, HAS_PART in the
  millions, plus per-type synset relation counts.
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

## Troubleshooting

- `environment variable 'OPENROUTER_API_KEY' is not set` -> add it to `.env`.
- `variant B needs a vector index at ...` -> run the `make index` step (config must
  match the one you run).
- `question validation failed` -> fix the listed lines in `questions.jsonl`.
- Docker/Postgres are only needed to *regenerate exports* (`make db`, `make core`);
  running and evaluating experiments does not need the database.
