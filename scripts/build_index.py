"""CLI (stub): build the text-RAG index - implemented in Phase 2.

Planned: one chunk per dictionary sense (lemma, POS, definition(s)), embedded
with the embedder configured in the experiment YAML; exact FAISS flat index;
chunks carry the same sense ids as variant C so citations are comparable.
"""

from __future__ import annotations

import sys


def main() -> int:
    print("build_index.py: not implemented yet (Phase 2).")
    return 2


if __name__ == "__main__":
    sys.exit(main())
