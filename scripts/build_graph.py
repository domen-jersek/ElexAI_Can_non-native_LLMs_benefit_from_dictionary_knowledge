"""CLI (stub): build the Neo4j knowledge graph - implemented in Phase 1.

Planned graph schema (draft, to be confirmed with the mentor):

    (:LexicalEntry {lemma, pos})-[:HAS_SENSE]->(:Sense {id, definition, order})
    (:Sense)-[:HAS_EXAMPLE]->(:Example {text})
    (:Sense)-[:SYNONYM_OF|ANTONYM_OF|HYPERNYM_OF]->(:Sense)
    (:Synset {id, ili}) linked to Sense via the OSWN-DDDS link table

with uniqueness constraints and indexes; loading must be idempotent and log
node/relationship counts by type.
"""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "build_graph.py: not implemented yet (Phase 1).\n"
        "Input: restored DDDS database in Postgres + OSWN data under data/raw/.\n"
        "See docs/DECISIONS.md and README.md status section."
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
