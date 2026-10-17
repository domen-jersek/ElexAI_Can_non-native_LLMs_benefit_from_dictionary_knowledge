# Decision log

Numbered, dated decisions with rationale. Newest at the bottom. If a decision is
revisited, add a new entry that supersedes the old one (do not rewrite history).

## D-001 (2026-10-15) - Primary dictionary: DDDS snapshot, not WordNet

The pilot needs one dictionary with trustworthy Slovene definitions and stable
sense ids. Verified during Phase 0:

- **DDDS snapshot (Postgres dump, backup v3.68, 2026-10-07)**: real Slovene
  lexicographic definitions (`jedro_definition.description`), senses with numeric
  ids, sense relations, morphology, resource/status grouping. This is the resource
  the task brief assumed might be inaccessible.
- **Open Slovene WordNet 1.0**: every synset has an EN definition (manual) but the
  Slovene definitions are all machine translations (`status="machine_translated"`).
  Fine for graph structure; not authoritative gold text.
- **sloWNet 3.1**: only 3,177 of 117,658 synsets have Slovene definitions and
  4,390 Slovene usage sentences. Reference only.

Decision: DDDS = the one dictionary (variants A/B/C and gold answers use DDDS sense
ids); OSWN = the structured/synset layer via the OSWN-DDDS link table; sloWNet kept
in the manifest for reference, Sloleks only for lemmatization.

## D-002 (2026-10-15) - Postgres staging + selective restore with privacy exclusions

The dump is a directory-format `pg_dump` of a production-like Django database
(102 tables, ~25 GB). Verdict: restore it into a local Postgres container
(`postgres:15.19-bookworm`, pinned) and work against SQL; do not parse the `.dat`
COPY files directly (joins/FKs/integrity make SQL dramatically simpler).

NOT restored (`EXCLUDED_TABLES` in `scripts/db_restore.py`):

- `auth_*`, `authtoken_token`, `django_*` (except `django_content_type`), `jet_*`:
  internal Django/admin data (users, sessions, logs) - privacy.
- `metadata_actionlog`, `metadata_comment`, `metadata_lexicalunitlog*`,
  `metadata_lexicalunitreindexrequest`, `metadata_mainmenuresourceviewsetting`:
  editor working notes/logs - privacy, not language description.
- `jedro_senseexampletoken` (~4 GB): token alignment positions; not needed for the
  pilot's question types.

`django_content_type` is kept because generic relations
(`jedro_object_feature`, `jedro_resourcerelevance`) reference it by content type id.

Restore is idempotent (skips if core tables exist; `--force` = drop schema, restore
again) and writes the exact TOC list used to `data/interim/ddds_restore.list`.

## D-003 (2026-10-15) - Pinned container images

`postgres:15.19-bookworm` (dump was produced by pg_dump 15.8; 15.x restores 15.x
archives; pinning the patch keeps the staging DB reproducible) and
`neo4j:5.26.32-community` (5.26 LTS line). Never use floating tags; bump
deliberately and note it here.

## D-004 (2026-10-15) - No hardcoded LLM / embedder / k; everything via configs

User requirement + reproducibility: every experiment is one YAML under `configs/`
validated by `src/elexai/config.py`. The embedder (name, HF id, revision), the LLM
(base_url, model, params) and retrieval `k`/sweep are config fields with sensible
defaults. Changing or comparing embedders must require zero code changes; run
manifests record the resolved values so results stay comparable after the fact.

Defaults for the first experiments (not yet run):

- LLM: `openai/gpt-6-luna` via OpenRouter (cheap, current tier; must be identical
  across A/B/C; exact model id + provider recorded per run).
- Embedder: `BAAI/bge-m3` (strong multilingual/Slovene coverage), revision to be
  pinned to a commit hash before real runs.
- Retrieval: exact FAISS flat search, `k=5` for generation, recall@k sweep
  `[1, 3, 5, 10]`, plus an oracle-context run.

## D-005 (2026-10-15) - API LLM, not local, for the pilot

Dev machine (i7-10510U, 24 GB RAM, Intel UHD, no CUDA) cannot serve a strong
Slovene-capable LLM usably. The OpenAI-compatible client (`base_url` in config)
keeps local vLLM/Ollama possible without code changes; the response cache keeps
published numbers reproducible offline.

## D-006 (2026-10-15) - Sentence text is NOT in the DDDS dump

The DDDS model references corpus sentences by id
(`jedro_examplesentence.corpus_sentence_id`) and fetches their text from a corpus
concordancer via an external API ("corpus data is not contained in the database
itself" - CJVT wiki data model page, v1.17). Consequences:

- Variant B chunks (one per sense) contain: lemma, POS, definition(s) - no corpus
  sentences.
- Question context sentences must come from somewhere else. Plan (to confirm with
  Klemen): hand-authored contexts, verified by a lexicographer. REMINDER for later
  phases: revisit before building the question set. Do not scrape the DDDS web UI.

## D-007 (2026-10-15) - Data layout and manifest

`data/raw/<subdir>` holds each source (gitignored); `data/MANIFEST.json` (committed)
records provenance + per-file sha256; `make data` verifies. `data/processed/` and
`runs/` are gitignored and regenerable; `data/questions/` is committed (small, the
scientific artifact). The DDDS dump keeps its original folder name
`gigabaza-003-068-2026q` (v3.**68**, 2026 Q4 release) for traceability.

## D-008 (2026-10-15) - Gold sense ids and citation scoring

Gold sense id = DDDS `jedro_sense.id` (string in the questions file). The
OSWN-DDDS link table was meant to resolve every gold id to an OSWN synset, but the
published 2023 list turned out to be stale against v3.68 (see D-012); synset-level
mapping is an open item and does not block the primary experiment. Questions carry
`review_status` (draft|verified) + reviewer; only lexicographer-verified questions
may be reported without a caveat.

## D-009 (2026-10-15) - Licensing and attribution

- sloWNet 3.1, OSWN 1.0, Sloleks 3.1: CC BY-SA 4.0; OSWN-DDDS link list: CC BY 4.0
  (attribution recorded in `data/MANIFEST.json` and docs/DATA.md).
- DDDS snapshot: no license is stated on the CJVT wiki distribution page. Treat as
  internal research use; never redistribute raw files or internal tables; confirm
  with the mentor before publishing anything derived beyond aggregate statistics.

## D-010 (2026-10-15) - Windows development environment

Primary dev machine is Windows: `uv` (winget), GNU make 3.81 (GnuWin32; `make` works
for the given targets), Docker Desktop required for Postgres/Neo4j. All commands in
docs/README use `uv run ...` and are shell-agnostic. `pre-commit` optional until the
repo lives on a server; lint/tests are the gate.

## D-011 (2026-10-15) - Postgres memory settings for the 12 GB Docker VM

Two issues surfaced while inspecting the restored snapshot:

1. Docker's default `/dev/shm` is 64 MB; parallel queries fail with
   `DiskFull: could not resize shared memory segment`. Fix: `shm_size: "2gb"` on the
   postgres service (docker-compose.yml).
2. A large parallel join over the multi-million-row tables OOM-killed a backend on
   the 12 GB VM, forcing a full crash recovery. Fix: heavy analytic scripts call
   `elexai.sources.ddds.prepare_analytics()` which disables per-gather parallelism and
   sets `work_mem = 128MB` per session, letting PostgreSQL spill to disk instead.

Both settings are conservative and documented; if the machine or the Docker VM memory
limit changes, revisit.

## D-012 (2026-10-15) - The 2023 OSWN<->DDDS link list is stale against v3.68

Verified in Phase 0: **none** of the 164,889 DDDS sense ids in the CLARIN.SI link
list (hdl 11356/1897, issued 2023-11-10) exist in the v3.68 snapshot - sense ids
were rebased (current real-sense ids run 8,149,410 - 16,661,707, including a
different set of ids in the same numeric band). 102,726 of the 164,889 lexical unit
ids still exist, and the linked forms are ordinary Slovene words.

Consequences:

- Gold sense ids in the question set are DDDS-native and need no link table.
- Variant C cannot use the published link list for DDDS-sense <-> OSWN-synset
  mapping as-is.

Options (needs Klemen, possibly CJVT):

1. Ask CJVT for a link list aligned with the current DDDS data.
2. Rebuild the mapping ourselves (forms + surviving lexical-unit ids + POS anchors).
3. Build variant C from DDDS structure only (sense relations, LU structure) and
   treat OSWN as optional enrichment.

Interim plan: implement variant C against DDDS structure; keep the OSWN layer
configurable so a re-linked mapping can be plugged in without code changes.

## D-013 (2026-10-16) - Sequencing amended: walking skeleton before any graph work

Per review feedback (and Claude's analysis of the pilot brief): variants A and B need
no graph at all, and the fastest way to learn whether there is signal is a thin
vertical slice. Decision: build the "walking skeleton" first (variants A, B, C and
oracle over the current dictionary core, LLM-free scoring, reports), then run it,
then decide further work with Klemen. Variant C is implemented over the structured
``lexical_core`` export behind the same retriever interface a graph backend would
use - the task wording is "strukturirane podatke oziroma graf", so Neo4j is a
possible later backend, not a prerequisite for the first results.

## D-014 (2026-10-16) - Evaluation protocol v1 (single template, per-variant primary metrics)

- One prompt template (`sd-v1`, `src/elexai/llm/prompts.py`) for ALL variants; the
  only difference between variant prompts is the context block (A renders "(Ni na
  voljo.)"). Recorded as `template_version` in every run manifest.
- Primary metric: **exact DDDS sense-ID citation** for variants B, C and oracle
  (the model must output `SENSE_ID: <id>`); variant A cannot cite ids and is scored
  by token-F1 of the free-text answer vs the gold answer (threshold configurable,
  default 0.6). Token-F1 is also reported for all variants.
- Oracle context = gold sense + up to `structured.oracle_max_candidates - 1`
  neighbouring senses of the same lemma: retrieval cannot fail by construction, so
  oracle failures are answer-composition errors.
- Error split: B = retrieval miss (gold not retrieved) vs composition; C = coverage
  miss (gold not among shown lemma senses) vs composition; B additionally reports
  recall@k. An optional LLM judge remains a later, separately-configured step.

## D-015 (2026-10-16) - Pinned first-run defaults

OpenRouter model `openai/gpt-6-luna` (cheap current tier; identical across variants,
temperature 0). Embedder for the real run: BGE-M3 @ commit
`5617a9f61b028005a4858fdac845db406aefb181`; smoke config uses multilingual-e5-small
@ `614241f622f53c4eeff9890bdc4f31cfecc418b3` with a 20k-chunk corpus limit (plumbing
only - smoke numbers are not meaningful). Retrieval: exact `faiss.IndexFlatIP`
(cosine, normalized), `k=5`, sweep `[1, 3, 5, 10]`.

## D-016 (2026-10-16) - Variant C context: collocations ("Zveze") from dependency relations

Data-driven choice: sense-level synonyms on definition-bearing senses are sparse in
DDDS (18,283 rows), while `dependency` sense relations - the typical collocations of
a sense ("kos kruha", "kos pogače") - are rich (986,354 kept across 84,641 senses;
export caps 24 per sense, prompts show up to 8). Hypernym/hyponym pairs are tiny
(5,414 / 3,890) and kept when present. C therefore renders "Sopomenke" (when any)
plus "Zveze"; B stays text-only (definition chunks) so the B/C contrast remains
"text search vs structured lookups".

## D-017 (2026-10-16) - LinkingTK spike: adopt WSA for the OSWN<->DDDS re-link

A timeboxed spike (isolated venv, `StringSimilarityLinker` + `LabelOverlap` blocking,
12 lemmas / 90 DDDS vs 61 OSWN senses) linked 84/90 DDDS senses; obvious senses
mapped correctly (mesec 3/3, most-bridge 1/1); bad pairs are cleanly separable by
score. Decision: if the mentor approves, run the full re-link (D-012 option 2) as a
scoped work package on top of LinkingTK - lemma blocking + string baseline +
optional embedding/LLM re-ranking - and emit a versioned, scored link table. The
toolkit's `Evaluator` is used only for that re-link task; the A/B/C experiment keeps
its own runner and scoring (D-014). Details: docs/LINKINGTK_SPIKE.md.

## D-018 (2026-10-17) - Variant D (graph RAG): design and load scope

Added as a fifth variant after the first evaluation round showed the two extremes
(B = pure semantic search fails mostly at retrieval; C = exact lookup is at the
oracle ceiling). Design: the SAME candidate universe as C (all loaded senses whose
first-part lemma matches; same cap of 12) but candidates are RANKED by how well the
sentence matches each sense's graph neighborhood - indicator+definition tokens
(weight 1), synonym words (weight 2) and typical-collocation forms (weight 2), with
the target lemma's own token excluded from scoring. Context rendering is
byte-identical to C's blocks, so the only difference between C and D is the ORDER of
candidates; the logged gold-rank is the graph's retrieval metric (analogue of
recall@k for B). Graph shape: (:Lexeme)-[:HAS_SENSE]->(:Sense) with
[:SYNONYM|ANTONYM|HYPERNYM|HYPONYM] between senses and
(:Sense)-[:COLLOCATES_WITH]->(:Phrase). The loader (scripts/load_graph.py) is
idempotent (MERGE) and runs against the user's Neo4j Desktop instance; the neo4j
driver is a runtime dependency of variant D only. Load scope: the 131k
definition-bearing senses; relations where both endpoints are loaded; ~986k
collocation edges. The WordNet synset layer is deliberately deferred to the
LinkingTK re-link (D-017) rather than a provisional lemma-level bridge.
