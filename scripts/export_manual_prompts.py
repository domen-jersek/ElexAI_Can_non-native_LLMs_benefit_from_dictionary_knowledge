"""CLI: export a copy-paste prompt kit for a chat-only model (manual runs).

    uv run python scripts/export_manual_prompts.py --run <run_id> --out manual_kit
    uv run python scripts/export_manual_prompts.py --config skeleton --variants A C D

Writes prompts.csv, answers.csv (to fill), one text file per prompt and a
HOWTO into ``--out`` (default ``manual_kit/``, gitignored). See
``src/elexai/manual.py`` for the whole workflow.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from elexai.env import REPO_ROOT
from elexai.manual import export_prompt_kit, latest_run


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", default=None, help="source run id (default: latest run of --config)")
    ap.add_argument("--config", default="skeleton", help="config name for the default source run")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "manual_kit")
    ap.add_argument("--variants", nargs="*", default=None, help="only these variants (e.g. A C D)")
    ap.add_argument(
        "--question-types",
        nargs="*",
        default=None,
        help="only these question types (sense_disambiguation / relation)",
    )
    args = ap.parse_args()

    source = args.run or latest_run(args.config)
    summary = export_prompt_kit(
        source,
        args.out,
        variants=args.variants,
        question_types=args.question_types,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nnext: fill {args.out / 'answers.csv'} (instructions: {args.out / 'HOWTO.md'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
