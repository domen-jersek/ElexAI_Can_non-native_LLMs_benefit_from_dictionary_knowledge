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

**How to run / regenerate**

```bash
uv sync    # dev group includes pandas, matplotlib, ipykernel, nbconvert
uv run jupyter nbconvert --to notebook --execute --inplace notebooks/0*.ipynb
```

The notebooks discover the latest run per config name (`skeleton`, `cap1`,
`cap2`, `cap3`); the latency figure pools the historical 22-question runs.
Figures are also saved to `notebooks/figures/`.

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
