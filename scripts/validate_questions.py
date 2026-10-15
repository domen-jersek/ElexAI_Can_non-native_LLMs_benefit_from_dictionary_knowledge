"""CLI: validate data/questions/questions.jsonl (structure + gold ids).

Usage:
    uv run python scripts/validate_questions.py
    uv run python scripts/validate_questions.py --questions data/questions/questions.jsonl
    uv run python scripts/validate_questions.py --senses data/processed/ddds/senses.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from elexai.questions import load_questions, load_senses_export, validate_questions

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--questions",
        type=Path,
        default=REPO_ROOT / "data" / "questions" / "questions.jsonl",
    )
    ap.add_argument(
        "--senses",
        type=Path,
        default=None,
        help="optional DDDS sense export (data/processed/ddds/senses.jsonl) for cross-checks",
    )
    args = ap.parse_args()

    if not args.questions.exists():
        print(f"question file not found: {args.questions}")
        return 1

    questions = load_questions(args.questions)
    senses = None
    if args.senses is not None:
        if args.senses.exists():
            senses = load_senses_export(args.senses)
        else:
            print(f"note: senses export not found ({args.senses}); skipping cross-checks")

    problems = validate_questions(questions, senses)
    n_draft = sum(1 for q in questions if q.review_status == "draft")
    n_verified = len(questions) - n_draft
    print(f"{len(questions)} questions ({n_verified} verified, {n_draft} draft)")
    if problems:
        print("PROBLEMS:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("validation OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
