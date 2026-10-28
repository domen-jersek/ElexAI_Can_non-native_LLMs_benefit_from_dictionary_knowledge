"""CLI: compare several runs (models) variant by variant.

    uv run python scripts/compare_runs.py 20261022-091557_skeleton \
        20261027-132531_gams3-12b_manual 20261028-095244_gams3-12b-rag_manual

Prints a markdown table (model x variant: citation accuracy, trick-excluded,
answer F1, retrieval/coverage and composition errors) plus the non-trick
questions each run's C/D variants missed. ``--csv`` also writes the table.

Manual (chat-UI) runs are single-sample and the served model is not
deterministic: repeated identical prompts changed the cited sense id in about
1 of 12 cases (see docs/DECISIONS.md D-027), so differences of one or two
questions on the 36-question set are within noise.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import pandas as pd

from elexai.analysis import accuracy_frame, load_answers
from elexai.env import REPO_ROOT

VARIANT_ORDER = ["A", "B", "C", "D", "oracle"]
CITATION_VARIANTS = ["B", "C", "D", "oracle"]


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float) and math.isnan(value):
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _fmt_count(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    return str(int(value))


def _print_table(acc: pd.DataFrame, run_order: dict[str, int]) -> None:
    acc = acc.copy()
    acc["_run"] = acc["run_id"].map(run_order)
    acc["_variant"] = acc["variant"].map({v: i for i, v in enumerate(VARIANT_ORDER)})
    acc = acc.sort_values(["_run", "_variant"])
    print("| model | variant | n | citation acc | excl. trick | answer F1 | retrieval/coverage err | composition err |")
    print("|---|---|---|---|---|---|---|---|")
    for _, r in acc.iterrows():
        print(
            f"| {r['model']} | {r['variant']} | {_fmt_count(r['n'])} | "
            f"{_fmt(r['citation_accuracy'])} | {_fmt(r['citation_accuracy_excl_trick'])} | "
            f"{_fmt(r['answer_f1_mean'])} | {_fmt_count(r['retrieval_errors'])} | "
            f"{_fmt_count(r['composition_errors'])} |"
        )


def _print_misses(run_ids: list[str]) -> None:
    print()
    print("Non-trick questions missed in C / D (single-sample runs - see the noise note):")
    for run_id in run_ids:
        df = load_answers(run_id)
        d = df[(df["variant"].isin(["C", "D"])) & (~df["is_trick"])].copy()
        d["ok"] = d["correct"].fillna(False).astype(bool)
        piv = d.pivot(index="question_id", columns="variant", values="ok")
        c_wrong = list(piv.index[~piv["C"]])
        d_wrong = list(piv.index[~piv["D"]])
        print(f"- {run_id}: C {c_wrong or 'none'} | D {d_wrong or 'none'}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("runs", nargs="+", help="run ids (or paths) to compare")
    ap.add_argument("--csv", type=Path, default=None, help="also write the table as CSV")
    args = ap.parse_args()

    run_ids = [Path(r).name for r in args.runs]
    acc = accuracy_frame(run_ids)
    run_order = {run_id: i for i, run_id in enumerate(run_ids)}
    _print_table(acc, run_order)
    _print_misses(run_ids)

    if args.csv:
        acc.to_csv(args.csv, index=False, encoding="utf-8")
        print(f"\nwritten: {args.csv}")
    print(
        "\nnote: manual/chat-UI runs are single-sample and not deterministic "
        "(~1 in 12 repeated prompts changed the cited id); treat differences of "
        "one or two questions as noise (docs/DECISIONS.md D-027)."
    )
    print(f"run dir: {REPO_ROOT / 'runs'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
