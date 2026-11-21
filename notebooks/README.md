# Analysis notebooks

The pilot's analysis story, told in five executed notebooks (English text,
classic light scientific figures). Everything here is derived from the run
artifacts under `runs/` and the committed question set - no LLM calls are made.

**Reading order**

| # | Notebook | What it answers |
|---|---|---|
| 1 | `01_setup_and_methods.ipynb` | The task mapped to the brief, the data (dictionary, variant C, the graph, variant B), a glossary of every term, a worked example, the four budgets. |
| 2 | `02_methods_head_to_head.ipynb` | The five methods compared across budgets: correctness, citations, response time, retrieval-vs-composition errors - plus the C≡D boundary case (when everything fits). |
| 3 | `03_when_does_the_graph_pay_off.ipynb` | The payoff rule (buried answer x lexical cue), validated on every question; expected gain vs measured gain; a decision checklist. |
| 4 | `04_relations.ipynb` | The second question type: explicit links, the retrieval trap, and the honest null result. |
| 5 | `05_cross_cutting.ipynb` | Citation taxonomy, the free-text metric for variant A, the difficulty profile, statistics (McNemar, bootstrap), limits and next steps. |
| 6 | `06_model_comparison.ipynb` | Four models on the same questions: the two API models (base `gpt-6-luna`, `gemini-4-argon`) vs the two Slovene GaMS 12B chat models (Instruct and its "-RAG" sibling), their error profiles, the figurative-sense failures, and the measured repeatability (noise floor ~1 question in 12). |
| 7 | `07_design_evaluation.ipynb` | The v2 **designed** set: the four sense cells and the relation cells, C vs D per cell across five models, the exact McNemar + Holm statistics, the `--b-lemma` repair, the budget curve, and an explicit section on what an oracle is and why it is not a mathematical ceiling. |
| 8 | `08_what_the_graph_buys.ipynb` | Five questions, one figure each: when the graph helps (cue dose-response), the two levers (search scope vs candidate order), the coverage cliff at position 4, a per-question map of who fails on what, and whether model size matters; plus a diagnosis table that separates "the model does not recognise the reading" from "the list/ranking failed". |
| 9 | `09_task_types_and_models.ipynb` | Four task types (sentence, definition, collocation, relation) under the same methods, the definition/collocation cells (buried/hidden), and the native-vs-non-native comparison - which turns out to be a tie in the aggregate, with the non-native advantage confined to the figurative subset. |

**How to run / regenerate**

```bash
uv sync    # dev group includes pandas, matplotlib, ipykernel, nbconvert
uv run jupyter nbconvert --to notebook --execute --inplace notebooks/0*.ipynb
```

The notebooks discover the latest run per config name (`skeleton`, `cap1`,
`cap2`, `cap3`, `gemini4-argon`, `gams3-12b`, `gams3-12b-rag`); the latency
figure pools the historical 22-question runs. Figures are also saved to
`notebooks/figures/`. The two GaMS runs are **manual (chat-UI) runs** - single
samples of a hosted product, not reproducible API calls; notebook 6 measures
their noise floor.

**Data sources**

- `runs/<run_id>/answers.jsonl` - per-answer records (prompts, shown/retrieved
  candidates, graph scores and matched features, gold ranks, latencies, cache
  flags); `metrics.json` - aggregated metrics per variant, question type and
  trick exclusion.
- `data/questions/questions.jsonl` - the question set (still **drafts**).
- `data/processed/ddds/lexical_core.jsonl` - sense definitions and positions.

All numbers are pilot signals: the questions are drafts until a lexicographer
verifies them, N is small, and single runs per regime. See
`docs/DECISIONS.md` (D-018..D-024) for methodology and known deviations.
