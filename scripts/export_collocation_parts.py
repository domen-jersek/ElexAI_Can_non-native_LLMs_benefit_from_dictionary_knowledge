"""CLI: export phrase -> component-word rows for graph part-edges (Part B).

For every collocation (dependency) form referenced by a real DDDS sense, emit
the phrase's component lexemes (lemma + category), so the graph loader can add

    (:Phrase)-[:HAS_PART]->(:Lexeme)

The form key is built identically to ``scripts/export_lexical_core.py``
(``COALESCE(NULLIF(lu2.form, ''), <first-part lemma>)``) so the rows join the
already-loaded Phrase nodes.

Requires Postgres (``make db`` once). Writes
``data/processed/ddds/collocation_parts.tsv`` (form, part_lemma, part_pos).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from elexai.sources.ddds import (
    ddds_connect,
    find_join_path,
    fk_edges,
    prepare_analytics,
    query,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "data" / "processed" / "ddds" / "collocation_parts.tsv"


def _join_fragment(conn, start_table: str, alias_prefix: str = "q") -> tuple[str, str]:
    path = find_join_path(fk_edges(conn), start_table, "jedro_lexeme")
    if not path:
        raise SystemExit(f"could not discover FK path {start_table} -> jedro_lexeme")
    joins: list[str] = []
    prev = "lu"
    for i, (tbl, ncol, pcol) in enumerate(path):
        alias = f"{alias_prefix}{i}"
        joins.append(f"JOIN {tbl} {alias} ON {alias}.{ncol} = {prev}.{pcol}")
        prev = alias
    return " ".join(joins), prev


def main() -> int:
    started = time.time()
    conn = ddds_connect(REPO_ROOT)
    prepare_analytics(conn)
    rel_join, rel_alias = _join_fragment(conn, "jedro_lexicalunit")

    print("querying phrase components (this can take a couple of minutes) ...", flush=True)
    rows = query(
        conn,
        f"""
        SELECT DISTINCT
               COALESCE(NULLIF(lu.form, ''), {rel_alias}.lemma) AS form,
               lex3.lemma AS part_lemma,
               COALESCE(cat3.name, '') AS part_pos
        FROM jedro_senserelation r
        JOIN jedro_senserelationtype t ON t.id = r.type_id
        JOIN jedro_sense s2 ON s2.id = r.to_sense_id
        JOIN jedro_lexicalunit lu ON lu.id = s2.lexical_unit_id
        {rel_join}
        JOIN jedro_lexicalunitpart p3 ON p3.lexical_unit_id = lu.id
        JOIN jedro_formencoding fe3 ON fe3.id = p3.form_encoding_id
        JOIN jedro_formrepresentation fr3 ON fr3.id = fe3.form_representation_id
        JOIN jedro_wordform wf3 ON wf3.id = fr3.word_form_id
        JOIN jedro_lexeme lex3 ON lex3.id = wf3.lexeme_id
        LEFT JOIN jedro_category cat3 ON cat3.id = lex3.category_id
        WHERE t.name = 'dependency'
          AND r.from_sense_id IN (
              SELECT id FROM jedro_sense WHERE position IS NOT NULL
          )
          AND (lu.form IS NOT NULL OR {rel_alias}.lemma IS NOT NULL)
        """,
    )
    conn.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="\n") as f:
        f.write("form\tpart_lemma\tpart_pos\n")
        for row in rows:
            f.write(f"{row['form']}\t{row['part_lemma']}\t{row['part_pos']}\n")

    n_forms = len({row["form"] for row in rows})
    print(f"wrote {len(rows)} rows ({n_forms} distinct forms) to {OUT}")
    print(f"elapsed: {time.time() - started:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
