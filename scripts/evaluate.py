"""CLI: evaluate one run (scoring is separate from generation).

    uv run python scripts/evaluate.py --last
    uv run python scripts/evaluate.py --run 20261016-121500_skeleton
    uv run python scripts/evaluate.py --run runs/20261016-121500_skeleton

Writes ``metrics.json`` and ``report.md`` into the run directory and prints a
short summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from elexai.eval.metrics import evaluate_run
from elexai.eval.report import build_report

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = REPO_ROOT / "runs"


def _resolve_run(value: str | None) -> Path:
    if value is None:
        candidates = sorted(
            (p for p in RUNS_DIR.iterdir() if p.is_dir()), key=lambda p: p.name
        )
        if not candidates:
            raise SystemExit(f"no runs found under {RUNS_DIR}")
        return candidates[-1]
    candidate = Path(value)
    if candidate.is_dir():
        return candidate
    candidate = RUNS_DIR / value
    if candidate.is_dir():
        return candidate
    raise SystemExit(f"run not found: {value}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", default=None, help="run directory or run id")
    ap.add_argument("--last", action="store_true", help="evaluate the most recent run")
    args = ap.parse_args()

    if args.run is None and not args.last:
        args.last = True
    run_dir = _resolve_run(None if args.last and args.run is None else args.run)

    metrics = evaluate_run(run_dir, REPO_ROOT)
    (run_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (run_dir / "report.md").write_text(build_report(run_dir, metrics), encoding="utf-8")

    print(f"run: {run_dir.name}  ({metrics['n_questions']} questions)")
    for variant, m in metrics["variants"].items():
        cite = m.get("citation_accuracy")
        cite_s = "-" if cite is None else f"{cite:.2f}"
        print(
            f"  {variant:6s}  citation_acc={cite_s}  answer_F1={m.get('answer_f1_mean')}  "
            f"p95={m.get('latency_p95_ms')}ms  errors={m.get('errors')}"
        )
    print(f"report: {run_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
