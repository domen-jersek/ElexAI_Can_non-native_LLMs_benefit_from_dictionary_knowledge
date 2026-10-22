# Analysis notebooks

The pilot's analysis story, told in five executed notebooks (English text,
classic light scientific figures). Everything here is derived from the run
artifacts under `runs/` and the committed question set - no LLM calls are made.

**Reading order**

| # | Notebook | What it answers |
|---|---|---|
| 1 | `01_setup_and_data.ipynb` | What do we compare, and what exactly does the model see in each variant? |
| 2 | `02_full_context.ipynb` | With all candidates visible, where does difficulty live? (Saturation, B's retrieval bottleneck, the two flawed items.) |
| 3 | `03_budget.ipynb` | What happens when the budget shrinks to 3/2/1 candidates? (Ordering becomes accuracy; the decisive questions; honest limits.) |
| 4 | `04_relations.ipynb` | Relation questions: the graph's home turf - and an honest null result. |
| 5 | `05_cross_cutting.ipynb` | Latency, the free-text metric, the difficulty profile, statistics, and the transferable claims. |

**How to run / regenerate**

```bash
uv sync    # dev group includes pandas, matplotlib, ipykernel, nbconvert
uv run jupyter nbconvert --to notebook --execute --inplace notebooks/0*.ipynb
```

The notebooks discover the latest run per config name (`skeleton`, `cap1`,
`cap2`, `cap3`); the latency notebook pools the historical 22-question runs.
Figures are also saved to `notebooks/figures/`.

**Data sources**

- `runs/<run_id>/answers.jsonl` - per-answer records (prompts, shown/retrieved
  candidates, graph evidence, gold ranks, latencies, cache flags);
  `metrics.json` - aggregated metrics per variant, question type and trick
  exclusion.
- `data/questions/questions.jsonl` - the question set (still **drafts**).
- `data/processed/ddds/lexical_core.jsonl` - sense definitions and positions.

All numbers are pilot signals: the questions are drafts until a lexicographer
verifies them, N is small, and single runs per regime. See
`docs/DECISIONS.md` (D-018..D-024) for methodology and known deviations.
