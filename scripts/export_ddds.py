"""CLI: export DDDS senses to JSONL (default: data/processed/ddds/senses.jsonl).

One record per sense:
  sense_id, position, lemma, pos, lu_form, lu_type, n_definitions, definition

Used by the question validator (gold-id cross-checks) and by later phases
(chunk building for variant B, graph loading for variant C). ``position`` is
NULL for the DDDS "dummy" senses; real senses of independent lexical units
have a position.

Usage:
    uv run python scripts/export_ddds.py [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from elexai.sources.ddds import ddds_connect, find_join_path, fk_edges, prepare_analytics

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "data" / "processed" / "ddds" / "senses.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument(
        "--all-senses",
        action="store_true",
        help="export every sense (incl. the ~8M null-position 'dummy' senses); "
        "default: only real senses with a position (independent units)",
    )
    args = ap.parse_args()

    conn = ddds_connect(REPO_ROOT)
    prepare_analytics(conn)
    path = find_join_path(fk_edges(conn), "jedro_lexicalunit", "jedro_lexeme")
    if not path:
        print("could not discover FK path jedro_lexicalunit -> jedro_lexeme")
        return 1

    joins: list[str] = []
    prev_alias = "lu"
    for i, (tbl, ncol, pcol) in enumerate(path):
        alias = f"p{i}"
        joins.append(f"JOIN {tbl} {alias} ON {alias}.{ncol} = {prev_alias}.{pcol}")
        prev_alias = alias
    lemma_col = f"{prev_alias}.lemma"
    lemma_join = " ".join(joins)

    where = "" if args.all_senses else "WHERE s.position IS NOT NULL"
    sql = f"""
        SELECT DISTINCT ON (s.id)
               s.id AS sense_id, s.position, {lemma_col} AS lemma,
               c.name AS pos, lu.form AS lu_form, lt.name AS lu_type,
               (SELECT count(*) FROM jedro_definition d
                 WHERE d.sense_id = s.id) AS n_definitions,
               (SELECT d.description FROM jedro_definition d
                 WHERE d.sense_id = s.id ORDER BY d.id LIMIT 1) AS definition
        FROM jedro_sense s
        JOIN jedro_lexicalunit lu ON lu.id = s.lexical_unit_id
        {lemma_join}
        LEFT JOIN jedro_category c ON c.id = {prev_alias}.category_id
        LEFT JOIN jedro_lexicalunittype lt ON lt.id = lu.type_id
        {where}
        ORDER BY s.id, p0.id
    """

    args.out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with conn.cursor() as cur:
        cur.execute(sql)
        if cur.description is None:  # pragma: no cover - misuse guard
            raise RuntimeError("cursor has no result description")
        cols = [d.name for d in cur.description]
        with args.out.open("w", encoding="utf-8", newline="\n") as f:
            for row in cur:
                f.write(json.dumps(dict(zip(cols, row, strict=True)), ensure_ascii=False) + "\n")
                n += 1
    conn.close()
    print(f"wrote {n} senses to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
