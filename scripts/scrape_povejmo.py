"""CLI: fill an answers CSV by driving the povejmo.si chat in a VISIBLE browser.

    # 1) inspect the UI once (sends nothing; dumps structure + screenshot)
    uv run python scripts/scrape_povejmo.py --inspect

    # 2) pilot: first unanswered row only, watch the window
    uv run python scripts/scrape_povejmo.py --csv manual_kit/answers_gams3-12b.csv ^
        --model "GaMS3-12B-Instruct" --limit 1

    # 3) the batch (resumable; already-answered rows are skipped)
    uv run python scripts/scrape_povejmo.py --csv manual_kit/answers_gams3-12b.csv ^
        --model "GaMS3-12B-Instruct"

Safety: the ONLY file modified is the CSV (atomic write + one-time .bak copy);
nothing is deleted; failures are stored in <csv folder>/scrape_debug/. See
src/elexai/scrape_povejmo.py for the full workflow.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from elexai.env import REPO_ROOT
from elexai.scrape_povejmo import PovejmoSession, run_batch

DEFAULT_CSV = REPO_ROOT / "manual_kit" / "answers.csv"
DEFAULT_PROFILE = REPO_ROOT / ".cache" / "povejmo_browser"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="answers CSV to fill")
    ap.add_argument("--model", default=None, help="exact model label from the povejmo.si dropdown")
    ap.add_argument("--limit", type=int, default=None, help="process at most N unanswered rows")
    ap.add_argument("--delay", type=float, default=10.0, help="pause between prompts (seconds)")
    ap.add_argument("--timeout", type=float, default=240.0, help="max wait per reply (seconds)")
    ap.add_argument("--stable", type=float, default=2.5, help="reply must be unchanged this long")
    ap.add_argument("--profile", type=Path, default=DEFAULT_PROFILE, help="browser profile folder")
    ap.add_argument("--debug-dir", type=Path, default=None, help="where to store debug artifacts")
    ap.add_argument("--headless", action="store_true", help="hide the browser window")
    ap.add_argument("--channel", default=None, help="browser channel, e.g. msedge")
    ap.add_argument("--inspect", action="store_true", help="dump the UI structure and exit")
    ap.add_argument("--dry-run", action="store_true", help="type one prompt but do NOT send it")
    args = ap.parse_args()

    debug_dir = args.debug_dir or (args.csv.parent / "scrape_debug")

    if args.inspect:
        session = PovejmoSession(
            profile_dir=args.profile, headless=args.headless, channel=args.channel
        )
        try:
            session.open()
            out = session.dump_inspect(debug_dir)
            print(f"inspect dump written to {out}")
        finally:
            session.close()
        return 0

    if not args.model:
        print("--model is required (exact label from the dropdown), e.g. \"GaMS3-12B-Instruct\"")
        return 1
    if not args.csv.exists():
        print(f"answers CSV not found: {args.csv}")
        return 1

    print(f"csv   : {args.csv}")
    print(f"model : {args.model}")
    print(f"debug : {debug_dir}")
    print("note  : only the CSV is modified (atomic write, one-time .bak backup)")
    stats = run_batch(
        csv_path=args.csv,
        model_label=args.model,
        profile_dir=args.profile,
        debug_dir=debug_dir,
        limit=args.limit,
        delay_s=args.delay,
        timeout_s=args.timeout,
        stable_s=args.stable,
        headless=args.headless,
        channel=args.channel,
        dry_run=args.dry_run,
    )
    print(f"done: processed={stats.processed} saved={stats.saved} failed={stats.failed}")
    return 0 if stats.failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
