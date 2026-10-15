"""CLI: remove local caches and regenerable artifacts (keeps raw data)."""

from __future__ import annotations

import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

TARGETS = [
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache",
    "runs", "data/interim",
]


def main() -> int:
    for t in TARGETS:
        p = REPO_ROOT / t
        if p.exists():
            shutil.rmtree(p)
            print(f"removed {t}/")
    for cache in REPO_ROOT.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    print("clean done (data/raw, data/processed, docs untouched)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
