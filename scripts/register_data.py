"""CLI: (re)hash raw source data into data/MANIFEST.json, or verify it.

Usage:
    uv run python scripts/register_data.py            # hash + write manifest
    uv run python scripts/register_data.py --verify   # check against manifest
    uv run python scripts/register_data.py --verify --only oswn sloleks
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from elexai.manifest import register, summary_line, verify

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verify", action="store_true", help="verify hashes against manifest")
    ap.add_argument("--only", nargs="*", default=None, help="restrict to these source ids")
    args = ap.parse_args()

    if args.verify:
        problems = verify(REPO_ROOT, only=args.only)
        if problems:
            print("MANIFEST VERIFICATION FAILED:")
            for p in problems:
                print(f"  - {p}")
            return 1
        print("manifest verification OK (all sizes and sha256 hashes match)")
        return 0

    manifest = register(REPO_ROOT, only=args.only, progress=lambda m: print(m, flush=True))
    print(f"manifest written to data/MANIFEST.json: {summary_line(manifest)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
