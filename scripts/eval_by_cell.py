"""Per-design-cell accuracy table for a run (the v2 designed question set).

The v2 set is stratified by mechanism (docs/DECISIONS.md D-030), so the useful
view is not one aggregate number but **one row per design cell**:

    S1_shallow_cued    all methods should work (calibration)
    S2_shallow_nocue   C wins by position; the model may still fail (composition)
    S3_buried_cued     C must fail, D must win (the payoff cell)
    S4_buried_nocue    C and D both fail (the rule's boundary)
    R_*_overlap        C can solve it from the definition overlap
    R_*_disjoint       only the explicit link (D) can solve it

    uv run python scripts/eval_by_cell.py --run <run_id>
    uv run python scripts/eval_by_cell.py --run <run_id> --csv cells.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from elexai.analysis import load_questions_table
from elexai.env import REPO_ROOT

VARIANT_ORDER = ["A", "B", "C", "D", "oracle"]
CITATION = ["B", "C", "D", "oracle"]


def load_per_question(run_dir: Path) -> pd.DataFrame:
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    return pd.DataFrame(metrics["per_question"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", required=True, help="run id (directory name under runs/)")
    ap.add_argument("--csv", type=Path, default=None, help="also write the long table")
    args = ap.parse_args()

    run_dir = REPO_ROOT / "runs" / args.run
    if not run_dir.is_dir():
        raise SystemExit(f"run not found: {run_dir}")

    pq = load_per_question(run_dir)
    qs = load_questions_table().set_index("question_id")
    pq = pq[pq["question_id"].isin(qs.index)].copy()
    pq["design_cell"] = pq["question_id"].map(qs["design_cell"])
    pq["phenomena"] = pq["question_id"].map(
        lambda q: ",".join(qs.loc[q, "phenomena"]) if isinstance(qs.loc[q, "phenomena"], list) else ""
    )
    missing = pq["design_cell"].isna() | (pq["design_cell"] == "")
    if missing.any():
        print(
            f"note: {int(missing.sum())} answers have no design_cell "
            f"(not a designed set?)",
            file=sys.stderr,
        )

    def correct(row: pd.Series) -> bool:
        if row["variant"] == "A":
            return bool(row.get("answer_correct"))
        return bool(row.get("citation_correct"))

    pq["correct"] = pq.apply(correct, axis=1)

    print(f"run: {args.run}")
    print(f"questions: {pq['question_id'].nunique()}  answers: {len(pq)}")
    print()
    print("accuracy per design cell (A = answer-text F1>=threshold, others = cited sense id):")
    table = (
        pq.pivot_table(index="design_cell", columns="variant", values="correct", aggfunc="mean")
        .reindex(columns=VARIANT_ORDER)
        .round(3)
    )
    counts = pq.groupby("design_cell")["question_id"].nunique().rename("n")
    print(table.join(counts).sort_index().to_string())

    print()
    print("C vs D per sense cell (the payoff rule):")
    sense = table[table.index.str.startswith("S")].copy()
    sense["D-C"] = (sense["D"] - sense["C"]).round(3)
    print(sense[["C", "D", "D-C"]].to_string())

    if (pq["phenomena"] != "").any():
        print()
        print("phenomena subgroups (mean over variants, citation variants only):")
        sub = pq[pq["variant"].isin(CITATION) & (pq["phenomena"] != "")]
        if not sub.empty:
            print(
                sub.pivot_table(
                    index="phenomena", columns="variant", values="correct", aggfunc="mean"
                )
                .reindex(columns=CITATION)
                .round(3)
                .to_string()
            )

    if args.csv:
        pq.to_csv(args.csv, index=False, encoding="utf-8")
        print(f"\nwritten: {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
