"""CLI: build the lexicographer review kit (sheet + table + summary).

    uv run python scripts/export_review_kit.py --run <run_id> --out review
    uv run python scripts/export_review_kit.py              # latest skeleton run

Writes ``review_sheet.md``, ``review_table.csv`` and ``review_summary.md``
(Slovene; see ``src/elexai/review.py``). The folder is gitignored.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from elexai.env import REPO_ROOT
from elexai.manual import latest_run
from elexai.review import build_review_kit


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", default=None, help="run id (default: latest run of --config)")
    ap.add_argument("--config", default="skeleton", help="config name for the default run")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "review")
    args = ap.parse_args()

    run_id = args.run or latest_run(args.config)
    summary = build_review_kit(run_id, args.out)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nreview kit written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
