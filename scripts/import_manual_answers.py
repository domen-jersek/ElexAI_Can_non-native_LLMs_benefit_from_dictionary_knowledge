"""CLI: import filled manual answers into a normal run directory.

    uv run python scripts/import_manual_answers.py --source-run <run_id> \
        --csv manual_kit/answers.csv \
        --model-label "GaMS3-12B-Instruct (manual via povejmo.si)"

Only rows with a non-empty ``answer_raw`` are imported; the run can be
re-imported later as more rows are filled. Afterwards:

    make eval RUN=<printed run id>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from elexai.env import REPO_ROOT
from elexai.manual import import_answers


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-run", required=True, help="run id whose prompts were exported")
    ap.add_argument("--csv", type=Path, default=REPO_ROOT / "manual_kit" / "answers.csv")
    ap.add_argument("--model-label", required=True, help="human-readable model label for the run")
    ap.add_argument("--name", default="gams", help="config name of the imported run")
    args = ap.parse_args()

    if not args.csv.exists():
        print(f"answers file not found: {args.csv}")
        return 1

    run_dir = import_answers(
        args.source_run, args.csv, model_label=args.model_label, name=args.name
    )
    print(f"imported run: {run_dir}")
    print(f"next: uv run python scripts/evaluate.py --run {run_dir.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
