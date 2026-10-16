"""CLI: build the exact (non-ANN) vector index for variant B.

    uv run python scripts/build_index.py --config configs/skeleton.yaml
    uv run python scripts/build_index.py --config configs/smoke.yaml --limit 2000

One index per (embedder id + pinned revision + corpus) under
``data/processed/index/<slug>/``; the runner loads it by the same slug.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from elexai.config import load_config
from elexai.retrieval.chunks import load_chunks
from elexai.retrieval.vector import build_index, get_embedder, index_slug

REPO_ROOT = Path(__file__).resolve().parents[1]
LEXICAL_CORE = REPO_ROOT / "data" / "processed" / "ddds" / "lexical_core.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument(
        "--limit", type=int, default=None, help="index only the first N chunks (dev/testing)"
    )
    args = ap.parse_args()

    cfg = load_config(args.config)
    limit = args.limit if args.limit is not None else cfg.retrieval.corpus_limit
    if not LEXICAL_CORE.exists():
        print(
            f"lexical core not found: {LEXICAL_CORE}\n"
            "run: uv run python scripts/export_lexical_core.py"
        )
        return 1

    chunks = load_chunks(LEXICAL_CORE)
    if limit is not None:
        chunks = chunks[:limit]
    print(f"chunks to index: {len(chunks)} (embedder: {cfg.embedder.hf_id} @ {cfg.embedder.revision})")

    embedder = get_embedder(cfg.embedder)
    out_dir = REPO_ROOT / cfg.index_dir / index_slug(cfg.embedder)
    meta = build_index(chunks, embedder, cfg.embedder, out_dir, LEXICAL_CORE, limit=limit)
    print(f"index written to {out_dir}")
    print(f"  dim={meta['dim']} n_chunks={meta['n_chunks']}")
    print("next: run an experiment, e.g.  uv run python -m elexai.runner configs/skeleton.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
